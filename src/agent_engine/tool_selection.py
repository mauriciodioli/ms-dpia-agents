"""Deterministic least-cost-sufficient recommendation. Never changes explicit pipelines."""
import math
from .auth import now_utc
from .contracts import utc
from .errors import EngineError


def select_candidate(candidates, *, now=None):
    now=now or now_utc()
    eligible=[]
    for candidate in candidates:
        if not candidate.get('authorized') or candidate.get('sufficient') is not True:continue
        try:
            if utc(candidate['valid_until'])<=now:continue
        except (KeyError,TypeError,EngineError):continue
        cost=candidate.get('cost')
        if cost is not None and (type(cost) not in (int,float) or not math.isfinite(cost) or cost<0):continue
        source=candidate.get('source')
        # Only free local evidence is preferred categorically. APIs/MCP/scraping
        # compete on known comparable cost and task-specific suitability.
        local=source=='local' and cost==0
        reasoning=source=='openai'
        eligible.append(((0 if local else 1,1 if reasoning else 0,cost is None,cost or 0,candidate['id']),candidate))
    return min(eligible,key=lambda item:item[0])[1] if eligible else None
