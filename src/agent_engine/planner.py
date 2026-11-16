"""Bounded AI planning. Produces proposals only; Dispatcher validates every tool.

Never invokes an MCP, scraper or analysis tool. Credentials stay server-side.
"""
import json
import logging
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
            from .provider_access import can_use
            if not can_use(self.conn,agent,provider):
                continue
            row = self.conn.execute(select(integrations).where(integrations.c.id == provider)).mappings().first()
            if row is not None and row['enabled'] and row['credential_ciphertext'] and identifier in self.registry.tools:
                result.append({'id': identifier, 'description': description,
                               'schema': self.registry.tools[identifier].input_schema, 'kind': kind})
        from .commercial import TOOL, DEPENDENCIES, configured
        if configured() and DEPENDENCIES.issubset({tool['id'] for tool in result}):
            result.append({'id': TOOL, 'kind': 'commercial_search',
                'description': 'Generate and validate a commercial search using the existing B2B OpenAI flow, then retrieve actual Amazon products through Apify. Prefer this for direct product discovery. It already includes commercial JSON generation: do not add web research or Analysis unless independently required. Requires the actual request location and postal/category context; never infer missing location from another task.',
                'schema': self.registry.tools[TOOL].input_schema})
        return result

    def plan(self, objective, agent, limits, job_id=None):
        if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000:
            raise EngineError('invalid_objective')
        from .provider_access import revoked
        if revoked(self.conn,agent,'openai'):raise EngineError('provider_access_revoked',403)
        tools = self.capabilities(agent)
        from .task_sources import allowed_tools
        selected = allowed_tools(self.conn, agent, self.registry)
        if selected is not None:
            tools = [tool for tool in tools if tool['id'] in selected]
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
        instructions = ('Never turn research headlines into commercial search queries. '
                        'Never fabricate URLs or ASINs; omit a future fetch if its real URLs are not known yet. '
                        'You are the DPIA execution planner. Return only a valid plan in JSON. '
                        'Choose the minimum necessary tools from the supplied catalog. Each parameters_json must be a JSON object encoded as a string matching that tool input schema. '
                        'Steps execute sequentially, and openai.analysis automatically receives earlier results. '
                        'Do not invent provider capabilities or placeholder URLs (example.com, example.org, example.net). '
                        'Search before reading pages. Only plan a fetch when real URLs are already present in the request; do not invent a binding to a future search result. '
                        'Never use Amazon to search jobs or local businesses. '
                        'Select by the tool capabilities and the complete objective, not by a fixed sequence. Prefer commercial_search for direct product discovery when available. Use web search for actual job offers and necessary research, never as a mandatory precursor to commercial_search. Do not add Analysis when retrieved structured evidence already answers the objective. commercial_search already generates the commercial JSON once. Its request.user_message must preserve the original objective exactly. Never invent missing postal or category IDs; use only supplied verified context. '
                        'Use analysis after data gathering only if comparison or synthesis is needed. '
                        'No side effects, purchasing, posting or credential handling. '
                        'Do not assume that a tool can receive previous results as input unless its schema allows it.')
        payload = {'objective':objective,'agent_instructions':agent['instructions'][:4000],
                   'available_tools':tools,'max_steps':max_steps,
                   'task_context':agent.get('_task_context',{})}
        if agent.get('_execution_sources') is not None:
            payload['execution_sources'] = agent['_execution_sources']
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
        self.omitted_steps = []
        for step in parsed['steps']:
            try:
                parameters = json.loads(step['parameters_json'])
            except (TypeError, ValueError):
                raise EngineError('planner_invalid_response', 502) from None
            if not isinstance(parameters, dict):
                raise EngineError('planner_invalid_response', 502)
            normalized = {'tool':step['tool'], 'parameters':parameters}
            from .adaptive_steps import real_reference, references
            if any(not real_reference(url) for url in references(parameters)):
                spec=self.registry.tools.get(step['tool'])
                if validated and spec and 'urls' in spec.input_schema.get('properties',{}):
                    self.omitted_steps.append({'tool':step['tool'],'reason':'planner_unsafe_reference'})
                    continue
                raise EngineError('planner_unsafe_reference',502)
            try:
                self.registry.validate_step(normalized,{t['id'] for t in tools})
            except EngineError as error:
                if error.code != 'invalid_contract':
                    raise
                # Only schema metadata is logged: never values, validation messages,
                # provider responses, credentials or arbitrary instance property names.
                from jsonschema import Draft202012Validator, FormatChecker
                spec=self.registry.tools.get(step['tool'])
                paths=[]
                required_fields=[]
                if spec is not None:
                    for failure in Draft202012Validator(spec.input_schema,format_checker=FormatChecker()).iter_errors(parameters):
                        path=list(failure.absolute_schema_path)
                        if failure.validator == 'required' and isinstance(failure.instance,dict):
                            missing=[index for index,key in enumerate(failure.validator_value) if key not in failure.instance]
                            paths.extend(path+[index] for index in missing[:5])
                            required_fields.extend(failure.validator_value[index] for index in missing[:5])
                        else:
                            paths.append(path)
                        if len(paths)>=5:break
                logging.getLogger(__name__).warning('Planner tool parameters invalid tool=%s schema_paths=%s required_fields=%s',
                    step['tool'],json.dumps(paths[:5],ensure_ascii=True),json.dumps(required_fields[:5],ensure_ascii=True))
                raise EngineError('planner_invalid_response',502) from None
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
