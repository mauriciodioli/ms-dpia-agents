"""MCP HTTP controllers. Shared session/Bearer authentication, no permissive CORS."""
from flask import current_app, request
from .api import api, endpoint, arguments, json_body, identifier, engine, page
from .auth import require_session_write
from .mcp_service import MCPService


def service():
    return current_app.extensions.get('mcp_service') or MCPService(engine(),current_app.config)


def write(principal):
    if principal.kind=='SESSION':require_session_write(principal,'manage-mcp')


@api.route('/mcp/servers',methods=['GET','POST'])
@endpoint()
def mcp_servers(conn,principal,repo):
    if request.method=='GET':
        arguments(('limit','after'));limit,after=page()
        return service().listing(principal,limit,after)
    arguments();write(principal)
    manager=service();server=manager.save(principal,json_body())
    diagnostic,status=manager.probe(principal,server['id'],{'expected_revision':server['revision']},discover=True)
    return {**diagnostic,'diagnostic_status':status},201


@api.route('/mcp/servers/<server_id>',methods=['GET','PATCH','DELETE'])
@endpoint()
def mcp_server(conn,principal,repo,server_id):
    arguments();identifier(server_id)
    if request.method=='GET':return service().detail(principal,server_id)
    write(principal)
    if request.method=='DELETE':return {'server':service().status(principal,server_id,json_body(),delete=True)}
    return {'server':service().save(principal,json_body(),server_id)}


@api.post('/mcp/servers/<server_id>/test')
@api.post('/mcp/servers/<server_id>/discover')
@endpoint()
def mcp_probe(conn,principal,repo,server_id):
    arguments();identifier(server_id);write(principal)
    return service().probe(principal,server_id,json_body(),discover=request.path.endswith('/discover'))


@api.patch('/mcp/servers/<server_id>/status')
@endpoint()
def mcp_status(conn,principal,repo,server_id):
    arguments();identifier(server_id);write(principal)
    return {'server':service().status(principal,server_id,json_body())}


@api.get('/mcp/servers/<server_id>/tools')
@endpoint()
def mcp_tools(conn,principal,repo,server_id):
    arguments();identifier(server_id)
    detail=service().detail(principal,server_id)
    return {'items':detail['tools'],'catalog_version':detail['server']['revision']}


@api.patch('/mcp/tools/<tool_id>')
@endpoint()
def mcp_tool(conn,principal,repo,tool_id):
    arguments();identifier(tool_id);write(principal)
    return service().update_tool(principal,tool_id,json_body())


@api.put('/mcp/tools/<tool_id>/grants/<agent_id>')
@endpoint()
def mcp_grant(conn,principal,repo,tool_id,agent_id):
    arguments();identifier(tool_id);identifier(agent_id);write(principal)
    return service().grant(principal,tool_id,agent_id,json_body())


@api.post('/agents/<agent_id>/source-selection')
@endpoint('jobs:create',write=True)
def source_selection(conn,principal,repo,agent_id):
    from .source_selection import recommend
    from .api import engine_write
    arguments();identifier(agent_id);engine_write(principal)
    return recommend(conn,principal,agent_id,json_body())
