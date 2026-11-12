"""Shared MCP business layer. No network inside database transactions."""
import json
import re
from hashlib import sha256
from uuid import uuid4, uuid5, NAMESPACE_URL
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from .auth import active_user, ADMIN_ROLES, now_utc
from .contracts import iso
from .errors import EngineError
from .integrations import IntegrationService
from .mcp_repository import MCPRepository, tool_id
from .mcp_transport import MCPClient, validate_url
from . import mcp_models as m

MCP_SCOPES=frozenset({'mcp:read','mcp:write','mcp:execute','mcp:approve'})
PRIVILEGED=ADMIN_ROLES | {'avanzado','advanced'}


def access(conn, principal, scope):
    principal.require(scope)
    role=str(active_user(conn,principal.owner_id)['roll']).strip().casefold()
    if role not in PRIVILEGED or scope=='mcp:approve' and role not in ADMIN_ROLES:
        raise EngineError('mcp_role_required',403)
    if principal.kind=='API_CLIENT' and not principal.all_agents and scope in ('mcp:write','mcp:approve'):
        raise EngineError('mcp_global_client_required',403)


def public_server(row):
    return {key:row[key] for key in ('id','name','description','endpoint_url','transport','auth_type','enabled','priority',
        'timeout_seconds','revision','last_health_status','last_error_code','connection_template')} | {
        'has_credential':bool(row['credential_ciphertext']),
        **{key:iso(row[key]) for key in ('last_checked_at','last_discovered_at','created_at','updated_at','deleted_at')}}


def public_tool(row):
    return {key:row[key] for key in ('id','server_id','tool_name','description','input_schema','enabled','risk_level','capability')} | {'catalog_id':tool_id(row['id'])}


def schema_hash(schema):
    return sha256(json.dumps(schema,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def safe_schema(schema):
    if not isinstance(schema,dict) or schema.get('type')!='object' or len(json.dumps(schema))>65536:
        raise EngineError('mcp_invalid_schema',422)
    count=0
    def walk(node,stack=(),depth=0):
        nonlocal count
        count+=1
        if depth>25 or count>4000:raise EngineError('mcp_invalid_schema',422)
        if isinstance(node,dict):
            if '$id' in node or '$dynamicRef' in node:raise EngineError('mcp_invalid_schema',422)
            ref=node.get('$ref')
            if ref is not None:
                if not isinstance(ref,str) or not ref.startswith('#/') or ref in stack:raise EngineError('mcp_invalid_schema',422)
                target=schema
                try:
                    for part in ref[2:].split('/'):target=target[part.replace('~1','/').replace('~0','~')]
                except (KeyError,TypeError):raise EngineError('mcp_invalid_schema',422) from None
                walk(target,stack+(ref,),depth+1)
            for value in node.values():walk(value,stack,depth+1)
        elif isinstance(node,list):
            for value in node:walk(value,stack,depth+1)
    walk(schema)
    try:Draft202012Validator.check_schema(schema)
    except SchemaError:raise EngineError('mcp_invalid_schema',422) from None
    return schema


class MCPService:
    def __init__(self, engine, config, *, client_factory=MCPClient):
        self.engine,self.config,self.client_factory=engine,config,client_factory
        self.secrets=IntegrationService(engine,config)

    @staticmethod
    def revision(body):
        value=body.get('expected_revision')
        if type(value) is not int or value<1:raise EngineError('invalid_contract')
        return value

    def encrypt(self, auth_type, credential):
        if auth_type=='none':return None
        if auth_type=='bearer':
            if not isinstance(credential,str) or not 1<=len(credential)<=8192 or any(ord(c)<33 or ord(c)>126 for c in credential):raise EngineError('invalid_contract')
        elif auth_type=='header':
            if not isinstance(credential,dict) or set(credential)!={'name','value'} or credential['name']!='X-API-Key':raise EngineError('invalid_contract')
            value=credential['value']
            if not isinstance(value,str) or not 1<=len(value)<=8192 or any(ord(c)<33 or ord(c)>126 for c in value):raise EngineError('invalid_contract')
        else:raise EngineError('invalid_contract')
        return self.secrets.cipher().encrypt(json.dumps(credential).encode()).decode()

    def credential(self, server):
        if server['auth_type']=='none':return None
        try:return json.loads(self.secrets.decrypt(server))
        except (ValueError,TypeError):raise EngineError('integration_encryption_unavailable',503) from None

    def listing(self, principal, limit=25, after=None):
        with self.engine.connect() as conn:
            access(conn,principal,'mcp:read');rows=MCPRepository(conn).listing(principal,limit,after)
            return dict(items=[public_server(r) for r in rows[:limit]],next_cursor=rows[limit-1]['id'] if len(rows)>limit else None)

    def detail(self, principal, identifier):
        with self.engine.connect() as conn:
            access(conn,principal,'mcp:read');repo=MCPRepository(conn)
            return dict(server=public_server(repo.server(identifier,principal)),tools=[public_tool(t) for t in repo.tools(identifier)])

    def save(self, principal, body, identifier=None):
        allowed={'name','description','endpoint_url','transport','auth_type','credential','enabled','timeout_seconds','priority','connection_template'}
        required={'name','endpoint_url','transport','auth_type','enabled','timeout_seconds','priority'}
        if identifier:allowed|={'expected_revision'};required|={'expected_revision'}
        if set(body)-allowed or required-set(body):raise EngineError('invalid_contract')
        if (not isinstance(body['name'],str) or not 1<=len(body['name'].strip())<=150
            or not isinstance(body.get('description',''),str) or len(body.get('description',''))>4000
            or body['transport']!='streamable_http' or body['auth_type'] not in ('none','bearer','header')
            or body['enabled'] is not False or type(body['priority']) is not int or not -32768<=body['priority']<=32767
            or type(body['timeout_seconds']) is not int or not 1<=body['timeout_seconds']<=120):raise EngineError('invalid_contract')
        template=body.get('connection_template')
        if template is not None:
            if not isinstance(template,dict) or len(json.dumps(template))>65536 or any(not isinstance(k,str) or not isinstance(v,dict) for k,v in template.items()):
                raise EngineError('invalid_contract',422)
        # Configuration changes are saved paused; a successful test/discovery precedes activation.
        url=validate_url(body['endpoint_url'])
        with self.engine.begin() as conn:
            access(conn,principal,'mcp:write');repo=MCPRepository(conn)
            previous=repo.server(identifier,principal,lock=True) if identifier else None
            if previous and previous['revision']!=self.revision(body):raise EngineError('revision_conflict',409)
            credential=previous['credential_ciphertext'] if previous else None
            if 'credential' in body:credential=self.encrypt(body['auth_type'],body['credential'])
            elif body['auth_type']=='none':credential=None
            elif not previous or previous['auth_type']!=body['auth_type'] or not credential:raise EngineError('mcp_credential_required',422)
            if 'connection_template' not in body and previous:
                template=previous['connection_template']
            now=now_utc();values=dict(connection_template=template,name=body['name'].strip(),description=body.get('description',''),endpoint_url=url,
                transport='streamable_http',auth_type=body['auth_type'],credential_ciphertext=credential,enabled=False,
                timeout_seconds=body['timeout_seconds'],priority=body['priority'],last_health_status='UNKNOWN',last_error_code=None,
                last_checked_at=None,last_discovered_at=None)
            if previous:
                row=repo.change_server(previous,principal.actor_id,**values)
                repo.revoke_server(identifier)
            else:
                identifier=str(uuid4());row=dict(id=identifier,revision=1,created_by=str(principal.owner_id),updated_by=principal.actor_id,
                    created_at=now,updated_at=now,deleted_at=None,**values);repo.insert(m.servers,row)
            repo.event(identifier,principal.actor_id,'SERVER_UPDATED' if previous else 'SERVER_CREATED')
            return public_server(row)

    def status(self, principal, identifier, body, *, delete=False):
        if set(body)!=({'expected_revision','confirm'} if delete else {'expected_revision','enabled'}):raise EngineError('invalid_contract')
        if delete and body['confirm'] is not True or not delete and type(body['enabled']) is not bool:raise EngineError('invalid_contract')
        with self.engine.begin() as conn:
            access(conn,principal,'mcp:write');repo=MCPRepository(conn);row=repo.server(identifier,principal,lock=True,deleted=delete)
            if delete and row['deleted_at']:return public_server(row)
            if row['revision']!=self.revision(body):raise EngineError('revision_conflict',409)
            enabled=False if delete else body['enabled']
            if enabled and (row['last_health_status']!='HEALTHY' or not row['last_discovered_at']):raise EngineError('mcp_not_ready',409)
            row=repo.change_server(row,principal.actor_id,enabled=enabled,**({'deleted_at':now_utc()} if delete else {}))
            if delete:repo.revoke_server(identifier)
            repo.event(identifier,principal.actor_id,'SERVER_DELETED' if delete else 'SERVER_ENABLED' if enabled else 'SERVER_PAUSED')
            return public_server(row)

    def probe(self, principal, identifier, body, *, discover=False):
        if set(body)!={'expected_revision'}:raise EngineError('invalid_contract')
        with self.engine.connect() as conn:
            access(conn,principal,'mcp:write');row=dict(MCPRepository(conn).server(identifier,principal))
            if row['revision']!=self.revision(body):raise EngineError('revision_conflict',409)
        result=None;error=None
        try:
            client=self.client_factory(row,self.credential(row)).initialize()
            if discover:result=self.validate_discovery(client.discover())
            else:client.rpc('ping')
        except EngineError as exc:error=exc
        with self.engine.begin() as conn:
            access(conn,principal,'mcp:write');repo=MCPRepository(conn);current=repo.server(identifier,principal,lock=True)
            if current['revision']!=row['revision']:raise EngineError('revision_conflict',409)
            values=dict(last_health_status='ERROR' if error else 'HEALTHY',last_error_code=error.code if error else None,last_checked_at=now_utc())
            if error:values['enabled']=False
            if discover and not error:
                values['last_discovered_at']=now_utc()
                existing={t['tool_name']:t for t in repo.tools(identifier)}
                names=set()
                for definition in result:
                    name=definition['name'];names.add(name);old=existing.get(name)
                    changed=old and (schema_hash(old['input_schema'])!=schema_hash(definition['inputSchema']) or (old['description'] or '')!=definition.get('description',''))
                    fields=dict(description=definition.get('description',''),input_schema=definition['inputSchema'],discovered_at=now_utc())
                    if old:
                        if changed:
                            fields.update(enabled=False,risk_level='HIGH');repo.revoke_tool(old['id'])
                        repo.change_tool(old['id'],**fields)
                    else:repo.insert(m.tools,dict(id=str(uuid5(NAMESPACE_URL,identifier+':'+name)),server_id=identifier,tool_name=name,
                        enabled=False,risk_level='HIGH',capability='mcp',updated_at=now_utc(),**fields))
                for name,old in existing.items():
                    if name not in names:
                        repo.change_tool(old['id'],enabled=False);repo.revoke_tool(old['id'])
            current=repo.change_server(current,principal.actor_id,**values)
            repo.event(identifier,principal.actor_id,'TOOLS_DISCOVERED' if discover else 'SERVER_TESTED',reason=error.code if error else None)
            response=dict(server=public_server(current),tools=[public_tool(t) for t in repo.tools(identifier)])
        if error:return response,error.status
        return response,200

    @staticmethod
    def validate_discovery(definitions):
        names=set()
        if not isinstance(definitions,list) or len(definitions)>200:raise EngineError('mcp_invalid_response',502)
        for item in definitions:
            if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,255}',item['name']) or item['name'] in names:raise EngineError('mcp_invalid_response',502)
            if not isinstance(item.get('description',''),str) or len(item.get('description',''))>8000:raise EngineError('mcp_invalid_response',502)
            safe_schema(item.get('inputSchema'));names.add(item['name'])
        return definitions

    def update_tool(self, principal, identifier, body):
        if set(body)!={'expected_revision','enabled','risk_level'} or type(body['enabled']) is not bool or body['risk_level'] not in ('LOW','MEDIUM','HIGH','CRITICAL'):raise EngineError('invalid_contract')
        with self.engine.begin() as conn:
            access(conn,principal,'mcp:write');repo=MCPRepository(conn);tool=repo.tool(identifier,principal)
            server=repo.server(tool['server_id'],principal,lock=True)
            if server['revision']!=self.revision(body):raise EngineError('revision_conflict',409)
            if tool['risk_level']!=body['risk_level']:
                access(conn,principal,'mcp:approve');repo.revoke_tool(identifier)
            if body['enabled'] and not server['last_discovered_at']:raise EngineError('mcp_not_ready',409)
            repo.change_tool(identifier,enabled=body['enabled'],risk_level=body['risk_level'])
            server=repo.change_server(server,principal.actor_id)
            repo.event(server['id'],principal.actor_id,'TOOL_UPDATED',tool=identifier,details={'enabled':body['enabled'],'risk_level':body['risk_level']})
            return dict(server=public_server(server),tool=public_tool(repo.tool(identifier)))

    def grant(self, principal, identifier, agent_id, body):
        if set(body)!={'expected_revision','enabled','owner_id','approved'} or type(body['enabled']) is not bool or type(body['approved']) is not bool or type(body['owner_id']) is not int:raise EngineError('invalid_contract')
        with self.engine.begin() as conn:
            access(conn,principal,'mcp:write');repo=MCPRepository(conn);tool=repo.tool(identifier,principal)
            owner=body['owner_id']
            if owner!=principal.owner_id and not principal.admin:raise EngineError('agent_not_found',404)
            if principal.kind=='API_CLIENT' and not principal.all_agents and agent_id not in principal.agent_ids:raise EngineError('agent_not_found',404)
            if not repo.agent(owner,agent_id):raise EngineError('agent_not_found',404)
            server=repo.server(tool['server_id'],principal,lock=True)
            if server['revision']!=self.revision(body):raise EngineError('revision_conflict',409)
            if body['enabled'] and tool['risk_level'] in ('HIGH','CRITICAL'):
                access(conn,principal,'mcp:approve')
                if body['approved'] is not True:raise EngineError('mcp_approval_required',403)
            repo.grant(owner,agent_id,identifier,body['enabled'],principal.actor_id)
            server=repo.change_server(server,principal.actor_id)
            repo.event(server['id'],principal.actor_id,'TOOL_GRANTED' if body['enabled'] else 'TOOL_REVOKED',tool=identifier,
                details={'owner_id':owner,'agent_id':agent_id,'approved':body['approved']})
            return {'server':public_server(server),'authorized':body['enabled']}
