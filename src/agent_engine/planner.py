"""Bounded AI planning. Produces proposals only; Dispatcher validates every tool.

Never invokes an MCP, scraper or analysis tool. Credentials stay server-side.
"""
import json
from sqlalchemy import select
from .errors import EngineError
from .integrations import IntegrationService
from .integration_models import integrations
from .provider_transport import OPENAI_BASE
from .mcp_repository import MCPRepository, tool_id
from . import models as m


def _response_text(response):
    texts = []
    for item in response.get('output', []):
        if isinstance(item, dict) and item.get('type') == 'message':
            for part in item.get('content', []):
                if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                    texts.append(part['text'])
    return '\n'.join(texts)


class Planner:
    def __init__(self, conn, *, service, registry):
        self.conn, self.service, self.registry = conn, service, registry
        self.usage_record = None

    def capabilities(self, agent):
        """Only tools that are currently enabled, implemented and executable."""
        result = []
        grants = set(self.conn.execute(select(m.agent_capabilities.c.tool_id).where(
            m.agent_capabilities.c.owner_id == agent['owner_id'],
            m.agent_capabilities.c.agent_id == agent['id'])).scalars())
        for row in MCPRepository(self.conn).catalog(agent['owner_id']):
            if row['risk_level'] != 'LOW' or row['tool_name'] not in ('web_search_exa', 'web_fetch_exa'):
                continue
            identifier = tool_id(row['id'])
            if identifier in self.registry.tools:
                result.append({'id': identifier, 'description': (row['description'] or row['tool_name'])[:700],
                               'schema': row['input_schema'], 'kind': 'web_search' if row['tool_name']=='web_search_exa' else 'web_fetch'})
        for identifier, provider, kind, description in (
            ('dpia.amazon.search', 'dpia-scraper', 'product_search', 'Structured Amazon product search with country and prices.'),
            ('openai.analysis', 'openai', 'analysis', 'Analyze and summarize previous step results.')):
            if identifier not in grants:
                continue
            row = self.conn.execute(select(integrations).where(integrations.c.id == provider)).mappings().first()
            if row is not None and row['enabled'] and row['credential_ciphertext'] and identifier in self.registry.tools:
                result.append({'id': identifier, 'description': description,
                               'schema': self.registry.tools[identifier].input_schema, 'kind': kind})
        return result

    def plan(self, objective, agent, limits, job_id=None):
        if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000:
            raise EngineError('invalid_objective')
        tools = self.capabilities(agent)
        if hasattr(self, 'permitted_tools'):
            tools = [tool for tool in tools if tool['id'] in self.permitted_tools]
        if not tools:
            raise EngineError('planner_no_available_tools', 409)
        config = self.service.row(self.conn, 'openai')
        if not config['enabled'] or not config['credential_ciphertext']:
            raise EngineError('planner_openai_not_configured', 409)
        self.service.valid_config('openai', config['config'])
        secret = self.service.decrypt(config)
        # The provider has no guaranteed pricing preflight. Bound output and steps.
        max_steps = min(limits['max_tool_calls'], 8)
        schema = {'type':'object','additionalProperties':False,'required':['steps'],
                  'properties':{'steps':{'type':'array','minItems':1,'maxItems':max_steps,
                  'items':{'type':'object','additionalProperties':False,'required':['tool','parameters_json'],
                  'properties':{'tool':{'type':'string','enum':[t['id'] for t in tools]},
                                'parameters_json':{'type':'string'}}}}}}
        instructions = ('You are the DPIA execution planner. Return only a valid plan in JSON. '
                        'Choose the minimum necessary tools from the supplied catalog. Each parameters_json must be a JSON object encoded as a string matching that tool input schema. '
                        'Steps execute sequentially, and openai.analysis automatically receives earlier results. '
                        'Do not invent provider capabilities or placeholder URLs (example.com, example.org, example.net). '
                        'Search before reading pages. Only plan a fetch when real URLs are already present in the request; do not invent a binding to a future search result. '
                        'Never use Amazon to search jobs or local businesses. '
                        'Use web search for general research; product search for Amazon products. '
                        'Use analysis after data gathering only if comparison or synthesis is needed. '
                        'No side effects, purchasing, posting or credential handling. '
                        'Do not assume that a tool can receive previous results as input unless its schema allows it.')
        payload = {'objective':objective,'agent_instructions':agent['instructions'][:4000],
                   'available_tools':tools,'max_steps':max_steps}
        if hasattr(self, 'task_instructions'):
            payload['task_instructions'] = self.task_instructions
        body = {'model':config['config']['model'],'store':False,'instructions':instructions,
                'input':json.dumps(payload,ensure_ascii=False),
                'max_output_tokens':min(1800,config['config']['max_output_tokens'],limits['max_output_tokens']),
                'text':{'format':{'type':'json_schema','name':'dpia_execution_plan',
                                  'strict':True,'schema':schema}}}
        if body['max_output_tokens'] < 250:
            raise EngineError('planner_insufficient_token_budget', 409)
        # A single POST avoids duplicate model charges when a request's outcome
        # is uncertain. Callers may retry with a new explicit request.
        response = self.service.http.request('POST', OPENAI_BASE + '/responses', secret,
            timeout=config['config']['timeout_seconds'], body=body)
        if response.get('status') != 'completed':
            raise EngineError('planner_incomplete_response', 502)
        try:
            parsed = json.loads(_response_text(response))
            from .contracts import validate
            validate(schema, parsed)
        except (ValueError, TypeError, KeyError, EngineError):
            raise EngineError('planner_invalid_response',502) from None
        # Validate against real schemas and reject hallucinated parameters.
        validated = []
        for step in parsed['steps']:
            try:
                parameters = json.loads(step['parameters_json'])
            except (TypeError, ValueError):
                raise EngineError('planner_invalid_response', 502) from None
            if not isinstance(parameters, dict):
                raise EngineError('planner_invalid_response', 502)
            normalized = {'tool':step['tool'], 'parameters':parameters}
            self.registry.validate_step(normalized,{t['id'] for t in tools})
            validated.append(normalized)
        # Defer usage persistence until Dispatcher has inserted ae_jobs.
        # ae_usage has a mandatory foreign key to ae_jobs.
        usage = response.get('usage')
        if isinstance(usage, dict):
            input_tokens, output_tokens = usage.get('input_tokens'), usage.get('output_tokens')
            if (type(input_tokens) is int and type(output_tokens) is int and
                    input_tokens >= 0 and output_tokens >= 0):
                self.usage_record = dict(provider_id='openai.responses',
                    provider_record_id=response.get('id'), verified=True,
                    evidence_source='PLANNER_RESPONSE', calls=1,
                    input_tokens=input_tokens, output_tokens=output_tokens)
        return validated
