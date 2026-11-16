"""Per-task execution source preferences over the existing authorized catalog."""
from sqlalchemy import select
from .errors import EngineError
from .mcp_catalog import uuid_for_tool
from .mcp_models import tools as mcp_tools, servers


def validate_preference(value):
    if (not isinstance(value, dict) or set(value) != {'mode', 'ids'}
            or value['mode'] not in ('all', 'selected') or not isinstance(value['ids'], list)
            or len(value['ids']) > 100 or any(not isinstance(x, str) or len(x) > 80 for x in value['ids'])
            or len(set(value['ids'])) != len(value['ids'])
            or (value['mode'] == 'all' and value['ids'])
            or (value['mode'] == 'selected' and not value['ids'])):
        raise EngineError('invalid_execution_sources', 422)
    return value


def source_for_tool(conn, identifier):
    if identifier == 'openai.analysis': return 'provider:openai'
    if identifier == 'dpia.amazon.search': return 'provider:dpia-scraper'
    if identifier.startswith('mcp.'):
        server = conn.execute(select(mcp_tools.c.server_id).where(
            mcp_tools.c.id == uuid_for_tool(identifier))).scalar_one_or_none()
        return 'mcp:' + server if server else None
    return None


def catalog(conn, agent, registry):
    from .planner import Planner
    available = Planner(conn, service=None, registry=registry).capabilities(agent)
    grouped = {}
    for tool in available:
        key = source_for_tool(conn, tool['id'])
        if not key: continue
        if key.startswith('mcp:'):
            name = conn.execute(select(servers.c.name).where(servers.c.id == key[4:])).scalar_one()
            kind = 'mcp'
        else:
            name = {'provider:openai':'OpenAI', 'provider:dpia-scraper':'DPIA Scraper'}[key]
            kind = 'provider'
        grouped.setdefault(key, {'id':key, 'name':name, 'kind':kind, 'tools':[]})['tools'].append(tool['id'])
    return sorted(grouped.values(), key=lambda item: (item['kind'], item['name'].casefold()))


def allowed_tools(conn, agent, registry):
    preference = agent.get('_execution_sources')
    if preference is None: return None
    validate_preference(preference)
    available = catalog(conn, agent, registry)
    by_id = {source['id']:source for source in available}
    selected = set(by_id) if preference['mode'] == 'all' else set(preference['ids'])
    if not selected or not selected.issubset(by_id):
        raise EngineError('selected_sources_unavailable', 409)
    result = {tool for key in selected for tool in by_id[key]['tools']}
    from .commercial import TOOL, DEPENDENCIES, configured
    if configured() and DEPENDENCIES.issubset(result): result.add(TOOL)
    return result
