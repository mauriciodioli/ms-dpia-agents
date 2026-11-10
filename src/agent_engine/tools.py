"""Declarative allowlist. Registration never imports or invokes provider code."""
from dataclasses import dataclass
from types import MappingProxyType
from .contracts import validate
from .errors import EngineError


@dataclass(frozen=True)
class ToolSpec:
    id: str
    provider: str
    capability: str
    input_schema: dict
    implementation_status: str
    contract_reference: str


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.id in self._tools:
            raise EngineError('duplicate_tool', 409)
        self._tools[tool.id] = tool

    @property
    def tools(self):
        return MappingProxyType(self._tools)

    def validate_step(self, step: dict, allowed: set[str]) -> None:
        tool = self._tools.get(step.get('tool'))
        if tool is None or tool.id not in allowed:
            raise EngineError('tool_not_authorized', 403)
        validate(tool.input_schema, step.get('parameters'))

    def validate_agent(self, definition: dict) -> None:
        from .contracts import AGENT_CREATE
        validate(AGENT_CREATE, definition)
        allowed = set(definition['capabilities'])
        if not allowed.issubset(self._tools):
            raise EngineError('unknown_capability')
        for tool_id, parameters in definition.get('tool_parameters', {}).items():
            self.validate_step({'tool': tool_id, 'parameters': parameters}, allowed)


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolSpec(
        id='dpia.test.echo', provider='local.test', capability='local-test',
        implementation_status='LOCAL_TEST_ONLY',
        contract_reference='agent_engine.demo_handler; no external network calls',
        input_schema={'type': 'object', 'additionalProperties': False,
                      'properties': {'message': {'type': 'string', 'maxLength': 500}}},
    ))
    registry.register(ToolSpec(
        id='dpia.amazon.search', provider='dpia.scraper', capability='search',
        implementation_status='IMPLEMENTED',
        contract_reference='agent_engine.provider_handlers; DPIA Scraper /base44/scraping',
        input_schema={
            'type': 'object', 'additionalProperties': False,
            'required': ['query', 'country'],
            'properties': {
                'query': {'type': 'string', 'minLength': 1, 'maxLength': 500},
                'max_products': {'type': 'integer', 'minimum': 1, 'maximum': 10},
                'country': {'enum': ['Argentina', 'Italia', 'España', 'Polonia', 'México', 'Uruguay']},
                'city': {'type': 'string', 'minLength': 1, 'maxLength': 100},
                'postal_id': {'type': 'integer', 'minimum': 1},
                'scope_id': {'type': 'integer', 'minimum': 1},
                'category_id': {'type': 'integer', 'minimum': 1},
                'language': {'enum': ['es', 'en', 'it', 'pl']},
            },
        },
    ))
    registry.register(ToolSpec(
        id='openai.analysis', provider='openai.responses', capability='analysis',
        implementation_status='IMPLEMENTED',
        contract_reference='agent_engine.provider_handlers; OpenAI /responses',
        input_schema={'type': 'object', 'additionalProperties': False,
                      'properties': {'instructions': {'type': 'string', 'maxLength': 8000}}},
    ))
    return registry
