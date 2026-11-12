"""Live, uncached MCP catalog and immutable per-job version evidence."""
from contextlib import contextmanager
from uuid import UUID
from .errors import EngineError
from .mcp_repository import MCPRepository, tool_id
from .mcp_service import schema_hash
from .tools import ToolSpec


def uuid_for_tool(identifier):
    try:
        if not identifier.startswith('mcp.'):raise ValueError()
        return str(UUID(hex=identifier[4:]))
    except (ValueError,TypeError,AttributeError):raise EngineError('mcp_invalid_tool',403) from None


def evidence(server,tool):
    return {'server_id':server['id'],'server_revision':server['revision'],'schema_hash':schema_hash(tool['input_schema']),
            'tool_name':tool['tool_name']}


def require_tool(conn, owner, agent, identifier, expected=None):
    server,tool=MCPRepository(conn).authorized(owner,agent,uuid_for_tool(identifier))
    current=evidence(server,tool)
    if expected is not None and expected!=current:raise EngineError('mcp_catalog_changed',409)
    return server,tool,current


class LiveRegistry:
    def __init__(self, base, conn=None, engine=None, owner=None):
        self.base,self.conn,self.engine,self.owner=base,conn,engine,owner

    def using(self,conn):
        return LiveRegistry(self.base,conn=conn,owner=self.owner)

    @property
    def tools(self):
        if self.conn is not None:rows=MCPRepository(self.conn).catalog(self.owner)
        else:
            with self.engine.connect() as conn:rows=MCPRepository(conn).catalog(self.owner)
        result=dict(self.base.tools)
        for row in rows:
            identifier=tool_id(row['id'])
            result[identifier]=ToolSpec(identifier,'mcp','mcp',row['input_schema'],'IMPLEMENTED','MCP Streamable HTTP; centrally enabled LOW tools')
        return result

    def validate_step(self,step,allowed):
        tool=self.tools.get(step.get('tool'))
        if not tool or tool.id not in allowed:raise EngineError('tool_not_authorized',403)
        from .contracts import validate
        validate(tool.input_schema,step.get('parameters'))

    def validate_agent(self,definition):
        from .contracts import AGENT_CREATE,validate
        validate(AGENT_CREATE,definition)
        if not set(definition['capabilities']).issubset(self.tools):raise EngineError('unknown_capability')
        for identifier,parameters in definition.get('tool_parameters',{}).items():
            self.validate_step({'tool':identifier,'parameters':parameters},set(definition['capabilities']))
