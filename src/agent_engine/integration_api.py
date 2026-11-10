"""Admin session-only integration API, using the engine's CSRF/origin policy."""
from flask import current_app, request
from .api import api, endpoint, engine, arguments, json_body
from .auth import require_session_write
from .integrations import IntegrationService, PROVIDERS


def service():
    return IntegrationService(engine(), current_app.config)


@api.get('/integrations')
@endpoint(admin_only=True)
def integration_list(conn, principal, repo):
    arguments()
    manager = service()
    return {'items': [manager.get(provider) for provider in PROVIDERS]}


@api.get('/integrations/<provider>')
@api.get('/integrations/<provider>/health')
@endpoint(admin_only=True)
def integration_status(conn, principal, repo, provider):
    arguments()
    return {'integration': service().get(provider)}


@api.put('/integrations/<provider>')
@endpoint(admin_only=True)
def integration_save(conn, principal, repo, provider):
    arguments()
    require_session_write(principal, 'manage-integrations')
    return {'integration': service().save(provider, json_body(), principal.actor_id)}


@api.post('/integrations/<provider>/enable')
@api.post('/integrations/<provider>/test')
@endpoint(admin_only=True)
def integration_test(conn, principal, repo, provider):
    arguments()
    require_session_write(principal, 'manage-integrations')
    enable = request.path.endswith('/enable')
    result, error = service().diagnose(provider, json_body(), principal.actor_id, enable=enable)
    return {'integration': result, 'error': error}, 409 if enable and error else 200


@api.post('/integrations/<provider>/disable')
@endpoint(admin_only=True)
def integration_disable(conn, principal, repo, provider):
    arguments()
    require_session_write(principal, 'manage-integrations')
    return {'integration': service().disable(provider, json_body(), principal.actor_id)}


@api.get('/integrations/<provider>/agents')
@endpoint(admin_only=True)
def integration_agents(conn, principal, repo, provider):
    from sqlalchemy import select, and_
    from . import models as m
    from .integrations import provider_spec
    arguments()
    spec = provider_spec(provider)
    # Assignment stays tenant-scoped: a global administrator does not silently
    # grant another owner's agents access to a shared paid credential.
    rows = conn.execute(select(m.agents).where(m.agents.c.owner_id == principal.owner_id)
        .order_by(m.agents.c.name).limit(100)).mappings().all()
    capable = set(conn.execute(select(m.agent_capabilities.c.agent_id).where(
        m.agent_capabilities.c.owner_id == principal.owner_id,
        m.agent_capabilities.c.tool_id == spec['tool'])).scalars())
    grants = set(conn.execute(select(m.tool_grants.c.agent_id).join(m.connections, and_(
        m.connections.c.owner_id == m.tool_grants.c.owner_id,
        m.connections.c.id == m.tool_grants.c.connection_id)).where(
            m.tool_grants.c.owner_id == principal.owner_id, m.tool_grants.c.tool_id == spec['tool'],
            m.connections.c.credential_ref == 'integration:' + provider,
            m.connections.c.enabled.is_(True))).scalars())
    return {'items': [{'id': r['id'], 'name': r['name'], 'enabled': r['configuration_state'] == 'ENABLED',
                       'has_capability': r['id'] in capable, 'authorized': r['id'] in grants} for r in rows]}


@api.put('/integrations/<provider>/agents/<agent_id>')
@endpoint(admin_only=True, write=True)
def integration_grant(conn, principal, repo, provider, agent_id):
    from uuid import uuid4, uuid5, NAMESPACE_URL
    from sqlalchemy import select, insert, delete
    from . import models as m
    from .auth import now_utc
    from .api import identifier
    from .errors import EngineError
    from .management import locked_agent, audit_agent
    from .integrations import provider_spec
    arguments()
    require_session_write(principal, 'manage-integrations')
    spec, body = provider_spec(provider), json_body()
    if set(body) != {'authorized', 'expected_revision'} or type(body['authorized']) is not bool:
        raise EngineError('invalid_contract')
    manager = service()
    expected = manager.revision(body)
    agent = locked_agent(conn, principal, identifier(agent_id))
    row = manager.row(conn, provider, lock=True)
    if row['revision'] != expected:
        raise EngineError('revision_conflict', 409)
    if not conn.execute(select(m.agent_capabilities.c.tool_id).where(
            m.agent_capabilities.c.owner_id == principal.owner_id,
            m.agent_capabilities.c.agent_id == agent_id,
            m.agent_capabilities.c.tool_id == spec['tool'])).first():
        raise EngineError('tool_not_authorized', 403)
    conn.execute(delete(m.tool_grants).where(m.tool_grants.c.owner_id == principal.owner_id,
        m.tool_grants.c.agent_id == agent_id, m.tool_grants.c.tool_id == spec['tool']))
    if body['authorized']:
        if not row['credential_ciphertext']:
            raise EngineError('integration_not_configured', 409)
        if not conn.execute(select(m.providers.c.id).where(m.providers.c.id == spec['provider'])).first():
            conn.execute(insert(m.providers).values(id=spec['provider'], kind=spec['capability'],
                registry_key=spec['tool'], contract_version='v1'))
        cid = str(uuid5(NAMESPACE_URL, f"agents-integration:{provider}:{principal.owner_id}"))
        if not conn.execute(select(m.connections.c.id).where(m.connections.c.id == cid)).first():
            conn.execute(insert(m.connections).values(id=cid, owner_id=principal.owner_id, provider_id=spec['provider'],
                name=provider, credential_ref='integration:' + provider, enabled=True, created_at=now_utc()))
        conn.execute(insert(m.tool_grants).values(owner_id=principal.owner_id, agent_id=agent_id,
            tool_id=spec['tool'], connection_id=cid))
    audit_agent(conn, principal, agent, 'PROVIDER_GRANTED' if body['authorized'] else 'PROVIDER_REVOKED',
                {'provider': spec['provider']}, now_utc())
    return {'authorized': body['authorized']}


@api.post('/integrations/dpia-scraper/trial')
@endpoint(admin_only=True, write=True)
def integration_trial(conn, principal, repo):
    from .dispatcher import Dispatcher
    from .repository import public_job
    from .api import identifier
    from .errors import EngineError
    from .integrations import require_enabled
    from .task_box import TaskBox
    arguments()
    require_session_write(principal, 'manage-integrations')
    body = json_body()
    if (set(body) != {'expected_revision', 'agent_id', 'query', 'country', 'max_products', 'confirm_cost'}
            or body['confirm_cost'] is not True):
        raise EngineError('cost_confirmation_required')
    manager = service()
    expected = manager.revision(body)
    # Agent lock first, matching the execution path lock order.
    from .management import locked_agent
    agent = locked_agent(conn, principal, identifier(body['agent_id']))
    row = manager.row(conn, 'dpia-scraper', lock=True)
    if row['revision'] != expected:
        raise EngineError('revision_conflict', 409)
    require_enabled(conn, 'dpia.scraper')
    ready = manager.readiness(conn, 'dpia-scraper', row)
    if not ready['worker_available']:
        raise EngineError('worker_unavailable', 409)
    timeout = row['config']['timeout_seconds']
    limits = {'max_tool_calls': 1, 'max_output_tokens': 1,
              'max_duration_seconds': timeout + 30, 'max_corrections': 0}
    payload = {'pipeline': [{'tool': 'dpia.amazon.search', 'parameters': {
        'query': body['query'], 'country': body['country'], 'max_products': body['max_products']}}],
        'limits': limits, 'instructions': 'Búsqueda administrativa de prueba, una consulta Amazon, sin publicación.'}
    job, created = Dispatcher(conn).submit(principal, agent['id'], payload, request.headers.get('Idempotency-Key'))
    # Validate the existing per-agent grant inside this same transaction; any
    # failure rolls back submission. Global enablement never grants all tenants.
    TaskBox(engine()).authorized(conn, job, {'tool_id': 'dpia.amazon.search'})
    return {'job': public_job(job), 'replayed': not created}, 202 if created else 200
