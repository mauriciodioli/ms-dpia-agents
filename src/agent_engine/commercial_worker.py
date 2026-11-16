"""Dedicated commercial Worker, on the existing Outbox/stream/lease runtime."""
from .worker import Worker, Handler, HandlerRegistry
from .commercial import TOOL, CommercialHandler
from .contracts import RESULT
from .errors import EngineError


def commercial_handlers(engine, config):
    from .provider_handlers import ProviderHandlers
    from .integrations import IntegrationService
    handlers = HandlerRegistry()
    handlers.register(TOOL, Handler(CommercialHandler(ProviderHandlers(IntegrationService(engine,config))), RESULT))
    return handlers


class CommercialWorker(Worker):
    def __init__(self, box, streams, handlers, **kwargs):
        if set(handlers.handlers) != {TOOL} or handlers.mcp_handler is not None:
            raise EngineError('commercial_requires_dedicated_worker',503)
        super().__init__(box, streams, handlers, ('commercial',), **kwargs)
