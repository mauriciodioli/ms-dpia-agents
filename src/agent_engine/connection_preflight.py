"""Read-only connectivity checks for scheduled pipelines; never invokes tools."""
from flask import current_app
from .errors import EngineError
from .integrations import IntegrationService, BY_PROVIDER
from .provider_transport import probe
from .mcp_catalog import require_tool
from .mcp_service import MCPService
from .mcp_transport import MCPClient


class ConnectionPreflight:
    def __init__(self, conn, registry):
        self.conn, self.registry = conn, registry
        self.service = IntegrationService(conn.engine, current_app.config)
        self.mcp_discovery = {}

    def check(self, agent, step):
        identifier = step['tool']
        if identifier.startswith('mcp.'):
            server, tool, _ = require_tool(self.conn, agent['owner_id'], agent['id'], identifier)
            # Initialization and discovery cannot execute a tool or spend its call budget.
            server = dict(server, timeout_seconds=min(server['timeout_seconds'], 5))
            if server['id'] not in self.mcp_discovery:
                try:
                    secret = MCPService(self.conn.engine, current_app.config).credential(server)
                    self.mcp_discovery[server['id']] = MCPClient(server, secret).initialize().discover()
                except EngineError as error:
                    self.mcp_discovery[server['id']] = error
            tools = self.mcp_discovery[server['id']]
            if isinstance(tools, EngineError):
                raise tools
            if not any(row.get('name') == tool['tool_name'] for row in tools):
                raise EngineError('mcp_tool_unavailable', 502)
            return ('mcp', server['id'])
        provider = self.registry.tools[identifier].provider
        key = BY_PROVIDER.get(provider)
        if key is None:
            if provider == 'local.test':
                return ('local', provider)
            raise EngineError('provider_unavailable', 502)
        row = self.service.row(self.conn, key)
        if not row['enabled'] or not row['credential_ciphertext']:
            raise EngineError('integration_disabled', 409)
        config = self.service.valid_config(key, row['config'])
        diagnostic = probe(key, config, self.service.decrypt(row), self.service.http)
        if not diagnostic['healthy'] or not diagnostic['permissions_ok']:
            raise EngineError(diagnostic['error'] or 'provider_unavailable', 502)
        return ('provider', key)

    def prepare(self, agent, pipeline):
        available, skipped, cache = [], [], {}
        for step in pipeline:
            identifier = step['tool']
            # Probe a provider once per trigger, retaining every available step in order.
            spec = self.registry.tools[identifier]
            if identifier.startswith('mcp.'):
                server, _, _ = require_tool(self.conn, agent['owner_id'], agent['id'], identifier)
                key = ('mcp', server['id'], identifier)
            else:
                key = ('provider', spec.provider)
            if key not in cache:
                try:
                    self.check(agent, step)
                    cache[key] = None
                except EngineError as error:
                    cache[key] = error.code
            if cache[key] is None:
                available.append(step)
            else:
                skipped.append({'tool': identifier, 'reason_code': cache[key]})
        return available, skipped
