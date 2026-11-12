"""One source for the MCP portal examples and executable OpenAPI operations."""
BASE='/api/agents/v1'
SERVER_ID='11111111-1111-4111-8111-111111111111'
TOOL_ID='22222222-2222-4222-8222-222222222222'
AGENT_ID='33333333-3333-4333-8333-333333333333'
CONFIG={'name':'DPIA Catalog','description':'Consulta de productos','endpoint_url':'https://mcp.example.com/mcp',
    'transport':'streamable_http','auth_type':'bearer','credential':'EXAMPLE_ONLY_REPLACE_TOKEN','enabled':False,'timeout_seconds':15,'priority':100}
SERVER={'id':SERVER_ID,'name':'DPIA Catalog','enabled':False,'last_health_status':'HEALTHY','revision':2,'has_credential':True}


def operations():
    tool={'id':TOOL_ID,'server_id':SERVER_ID,'tool_name':'catalog.search','enabled':False,'risk_level':'HIGH','input_schema':{'type':'object'},'catalog_id':'mcp.'+TOOL_ID.replace('-','')}
    rows=[
        ('get','/mcp/servers','Listar servidores','mcp:read',None,{'items':[SERVER],'next_cursor':None},200),
        ('post','/mcp/servers','Registrar, probar y descubrir','mcp:write',CONFIG,{'server':SERVER,'tools':[tool],'diagnostic_status':200},201),
        ('get','/mcp/servers/{server_id}','Consultar configuración y herramientas','mcp:read',None,{'server':SERVER,'tools':[tool]},200),
        ('patch','/mcp/servers/{server_id}','Editar y pausar; revoca permisos anteriores','mcp:write',{**CONFIG,'expected_revision':2},{'server':{**SERVER,'revision':3,'last_health_status':'UNKNOWN'}},200),
        ('delete','/mcp/servers/{server_id}','Eliminar lógicamente y revocar herramientas','mcp:write',{'expected_revision':2,'confirm':True},{'server':{**SERVER,'revision':3,'deleted_at':'2026-11-12T12:00:00Z'}},200),
        ('post','/mcp/servers/{server_id}/test','Probar conexión sin invocar herramientas','mcp:write',{'expected_revision':2},{'server':{**SERVER,'revision':3},'tools':[tool]},200),
        ('post','/mcp/servers/{server_id}/discover','Descubrir y validar metadatos sin ejecutar herramientas','mcp:write',{'expected_revision':2},{'server':{**SERVER,'revision':3},'tools':[tool]},200),
        ('patch','/mcp/servers/{server_id}/status','Activar después de diagnóstico y descubrimiento','mcp:write',{'expected_revision':2,'enabled':True},{'server':{**SERVER,'revision':3,'enabled':True}},200),
        ('patch','/mcp/servers/{server_id}/status','Pausar inmediatamente','mcp:write',{'expected_revision':3,'enabled':False},{'server':{**SERVER,'revision':4,'enabled':False}},200),
        ('get','/mcp/servers/{server_id}/tools','Listar herramientas y versión del catálogo','mcp:read',None,{'items':[tool],'catalog_version':2},200),
        ('patch','/mcp/tools/{tool_id}','Habilitar/deshabilitar herramienta y revisar riesgo','mcp:write',{'expected_revision':2,'enabled':True,'risk_level':'HIGH'},{'server':{**SERVER,'revision':3},'tool':{**tool,'enabled':True}},200),
        ('put','/mcp/tools/{tool_id}/grants/{agent_id}','Autorizar agente; HIGH/CRITICAL requieren aprobación','mcp:write',{'expected_revision':3,'enabled':True,'owner_id':22,'approved':True},{'server':{**SERVER,'revision':4},'authorized':True},200),
        ('put','/mcp/tools/{tool_id}/grants/{agent_id}','Revocar permiso de agente','mcp:write',{'expected_revision':4,'enabled':False,'owner_id':22,'approved':False},{'server':{**SERVER,'revision':5},'authorized':False},200),
    ]
    result=[]
    for method,path,title,scope,body,response,status in rows:
        network=method=='post' and (path.endswith(('/test','/discover')) or path=='/mcp/servers')
        codes=[400,401,403,503]
        if '{' in path:codes += [404,409]
        if network or method=='patch' and path.endswith('{server_id}'):codes += [422]
        if network:codes += [502]
        errors={str(code):{'error':{400:'invalid_contract',401:'authentication_required',403:'mcp_role_required',404:'mcp_server_not_found',409:'revision_conflict',422:'mcp_invalid_url',502:'mcp_transport_error',503:'engine_storage_unavailable'}[code],'api_version':'agents.v1'} for code in codes}
        result.append(dict(method=method.upper(),path=BASE+path,relative_path=path,title=title,scope=scope,body=body,
            response={'api_version':'agents.v1','snapshot_at':'2026-11-12T12:00:00Z',**response},success_status=status,errors=errors))
    return result


def add_openapi(paths):
    for op in operations():
        method=op['method'].lower();path=op['relative_path']
        parameters=[{'name':key,'in':'path','required':True,'schema':{'type':'string','format':'uuid'}} for key in ('server_id','tool_id','agent_id') if '{'+key+'}' in path]
        if method=='get' and path=='/mcp/servers':parameters += [{'name':'limit','in':'query','schema':{'type':'integer','minimum':1,'maximum':100,'default':25}}, {'name':'after','in':'query','schema':{'type':'string','format':'uuid'}}]
        if op['body'] is not None:parameters += [{'name':'X-DPIA-Action','in':'header','description':'Required for cookie sessions only: manage-mcp','schema':{'const':'manage-mcp'}}]
        entry={'tags':['MCP — Servidores y herramientas'],'summary':op['title'],'x-required-scope':op['scope'],
            'description':'ADMINISTRADOR o AVANZADO. Sesión o Bearer. API clients need all_agents for MCP mutations. HIGH/CRITICAL grants and risk changes also require mcp:approve and administrator role. Secrets are never returned. expected_revision is the server/catalog revision. Header auth uses credential={name:X-API-Key,value:...}.',
            'parameters':parameters,'responses':{str(op['success_status']):{'description':'Success; no tool invocation during management','content':{'application/json':{'example':op['response']}}},
                **{code:{'description':value['error'],'content':{'application/json':{'example':value}}} for code,value in op['errors'].items()}}}
        if op['body'] is not None:
            entry['requestBody']={'required':True,'content':{'application/json':{'example':op['body'],'schema':input_schema(op)}}}
        if path not in paths or method not in paths[path]:paths.setdefault(path,{})[method]=entry


def input_schema(op):
    properties={}
    for key,value in op['body'].items():
        if key=='credential':properties[key]={'oneOf':[{'type':'string','maxLength':8192},{'type':'object','required':['name','value'],'additionalProperties':False,'properties':{'name':{'const':'X-API-Key'},'value':{'type':'string','maxLength':8192}}}]}
        else:properties[key]={'type':'boolean' if type(value) is bool else 'integer' if type(value) is int else 'string'}
    for key,limits in {'expected_revision':{'minimum':1},'timeout_seconds':{'minimum':1,'maximum':120},'priority':{'minimum':-32768,'maximum':32767},'name':{'minLength':1,'maxLength':150},'description':{'maxLength':4000},'endpoint_url':{'format':'uri','maxLength':2048}}.items():
        if key in properties:properties[key].update(limits)
    for key,enum in {'transport':['streamable_http'],'auth_type':['none','bearer','header'],'risk_level':['LOW','MEDIUM','HIGH','CRITICAL']}.items():
        if key in properties:properties[key]['enum']=enum
    required=[key for key in properties if key not in ('credential','description')]
    return {'type':'object','additionalProperties':False,'required':required,'properties':properties}
