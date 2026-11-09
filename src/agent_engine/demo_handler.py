"""Explicitly opt-in local-only worker for smoke tests. Never verifies evidence."""
from .worker import Handler, HandlerRegistry

def demo_handlers():
    handlers = HandlerRegistry()
    handlers.register('dpia.test.echo', Handler(
        run=lambda context, parameters: {
            'schema_version': 'agents.result.v1',
            'summary': 'Prueba interna: ' + parameters.get('message', 'Flujo DPIA Agents'),
            'findings': [],
            'sources': [],
            'warnings': ['Resultado simulado: sin evidencia externa ni aprobación automática.'],
        },
        output_schema={
            'type': 'object',
            'required': ['schema_version', 'summary', 'findings', 'sources', 'warnings'],
            'properties': {
                'schema_version': {'const': 'agents.result.v1'},
                'summary': {'type': 'string'},
                'findings': {'type': 'array'},
                'sources': {'type': 'array'},
                'warnings': {'type': 'array'},
            },
            'additionalProperties': False,
        },
        requires_provider_grant=False,
    ))
    return handlers
