"""REST and existing HMAC adapters for the tested logical-deletion domain."""
from uuid import UUID,uuid5,NAMESPACE_URL
from flask import jsonify
from sqlalchemy import select
from .api import api,endpoint,engine,engine_write,arguments,json_body,identifier
from .auth import active_user,Principal
from .management import AgentManager
from .errors import EngineError
from .pwa_activation import verify_hmac
from . import models as m

PATH='/api/agents/v1/internal/pwa-delete'

@api.delete('/agents/<agent_id>')
@endpoint('agents:delete',write=True)
def delete_owner(conn,principal,repo,agent_id):
    arguments();engine_write(principal)
    AgentManager(conn,principal).delete_agent(identifier(agent_id),json_body(),interface='agents-api' if principal.kind=='API_CLIENT' else 'agents')
    return {},204

@api.delete('/admin/agents/<agent_id>')
@endpoint(admin_only=True,write=True)
def delete_admin(conn,principal,repo,agent_id):
    arguments();engine_write(principal)
    AgentManager(conn,principal).delete_agent(identifier(agent_id),json_body(),interface='agents-admin')
    return {},204

@api.post('/internal/pwa-delete')
def delete_pwa():
    verify_hmac(PATH);arguments();body=json_body()
    if (set(body)!={'owner_id','source_agent_id','source_revision','agent_id','command'} or
            type(body['owner_id']) is not int or body['owner_id']<1 or not isinstance(body['command'],dict)):
        raise EngineError('invalid_contract')
    command=body['command']
    if set(command)!={'confirm','expected_revision','operation_id'} or command.get('confirm') is not True:
        raise EngineError('invalid_contract')
    try:
        if str(UUID(command['operation_id']))!=command['operation_id']:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise EngineError('invalid_operation_id') from None
    with engine().begin() as conn:
        active_user(conn,body['owner_id'])
        previous=conn.execute(select(m.agent_deletions).where(m.agent_deletions.c.owner_id==body['owner_id'],
            m.agent_deletions.c.operation_id==command['operation_id'])).mappings().first()
        if previous:result=previous
        else:
            if (type(body['source_agent_id']) is not int or body['source_agent_id']<1 or
                    type(body['source_revision']) is not int or body['source_revision']<1):
                raise EngineError('invalid_contract')
            native=None
            if body['agent_id'] is None:
                native=conn.execute(select(m.agents).where(m.agents.c.owner_id==body['owner_id'],
                    m.agents.c.legacy_agent_id==body['source_agent_id']).with_for_update()).mappings().first()
                if native:agent_id=native['id'];command={**command,'expected_revision':native['revision']}
                else:agent_id=str(uuid5(NAMESPACE_URL,f"dpia:draft:{body['owner_id']}:{body['source_agent_id']}:{body['source_revision']}"))
            else:agent_id=identifier(body['agent_id'])
            principal=Principal(body['owner_id'],'PWA_SERVICE',str(body['owner_id']),frozenset({'agents:delete'}),True,frozenset())
            result=AgentManager(conn,principal).delete_agent(agent_id,command,interface='b2b',source_id=body['source_agent_id'],
                source_revision=body['source_revision'],draft=body['agent_id'] is None and native is None)
    return jsonify(api_version='agents.v1',deleted=True,agent_id=result['agent_id'],owner_id=result['owner_id'],
        source_agent_id=result['legacy_agent_id'],execution_enabled=False)
