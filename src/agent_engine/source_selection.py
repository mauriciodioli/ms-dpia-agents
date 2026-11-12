"""Owner-scoped local evidence first; comparable source estimates, no automatic calls."""
import math
import re
from datetime import timedelta
from .auth import now_utc
from .contracts import iso, utc
from .errors import EngineError
from .repository import ReadRepository
from .tools import default_registry
from .tool_selection import select_candidate
from .mcp_catalog import require_tool


def recommend(conn, principal, agent_id, body):
    if set(body)!={'required_terms','fresh_seconds','currency','candidates'}:raise EngineError('invalid_contract')
    terms=body['required_terms'];fresh=body['fresh_seconds'];candidates=body['candidates']
    if (not isinstance(terms,list) or not 1<=len(terms)<=20 or any(not isinstance(t,str) or not 1<=len(t)<=100 for t in terms)
        or type(fresh) is not int or not 1<=fresh<=86400 or not isinstance(body['currency'],str)
        or not re.fullmatch('[A-Z]{3}',body['currency']) or not isinstance(candidates,list) or len(candidates)>30):raise EngineError('invalid_contract')
    repository=ReadRepository(conn,principal)
    repository.agent(agent_id);now=now_utc()
    rows=repository.local_source_results(agent_id,now-timedelta(seconds=fresh))
    options=[]
    for row in rows:
        text=json_text(row['payload']).casefold()
        options.append(dict(id='local.'+row['id'],source='local',authorized=True,sufficient=all(t.casefold() in text for t in terms),
            valid_until=iso(row['created_at']+timedelta(seconds=fresh)),cost=0,currency=body['currency'],result_id=row['id']))
    registry=default_registry(conn=conn,owner=principal.owner_id)
    caps=repository.capabilities(agent_id)
    for candidate in candidates:
        if not isinstance(candidate,dict) or set(candidate)!={'tool','sufficient','valid_until','estimated_cost'} or type(candidate['sufficient']) is not bool:raise EngineError('invalid_contract')
        cost=candidate['estimated_cost']
        if cost is not None and (type(cost) not in (float,int) or not math.isfinite(cost) or cost<0):raise EngineError('invalid_contract')
        until=utc(candidate['valid_until'])
        spec=registry.tools.get(candidate['tool'])
        if not spec or spec.id not in caps:raise EngineError('tool_not_authorized',403)
        if spec.provider=='mcp':principal.require('mcp:execute');require_tool(conn,principal.owner_id,agent_id,spec.id)
        options.append(dict(id=spec.id,source={'mcp':'mcp','openai.responses':'openai','dpia.scraper':'scraping'}.get(spec.provider,'api'),
            authorized=True,sufficient=candidate['sufficient'],valid_until=iso(until),cost=cost,currency=body['currency']))
    selected=select_candidate(options,now=now)
    return {'selection':selected,'policy':'least_cost_sufficient','execution_enabled':False,
            'basis':'Local freshness and term matching; remote sufficiency/cost are caller estimates, not charges.'}


def json_text(value):
    import json
    return json.dumps(value,ensure_ascii=False)
