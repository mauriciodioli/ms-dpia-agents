"""Independent user/admin pause flags in existing audit. No jobs are launched."""
from dataclasses import replace
from uuid import UUID
from sqlalchemy import select, update
from . import models as m
from .auth import now_utc, active_user, Principal
from .errors import EngineError
from .management import locked_agent, audit_agent
from .api import api, endpoint, engine, engine_write, arguments, json_body, identifier
from .repository import ReadRepository

PATH = '/api/agents/v1/internal/pwa-pause'
ACTION = 'AGENT_PAUSE_CHANGED'


def pause_state(conn, row):
    details = conn.execute(select(m.agent_events.c.details).where(
        m.agent_events.c.owner_id == row['owner_id'], m.agent_events.c.agent_id == row['id'],
        m.agent_events.c.action == ACTION).order_by(m.agent_events.c.revision.desc()).limit(1)).scalar_one_or_none()
    return {k: details[k] for k in ('user_paused', 'admin_paused')} if details else dict(user_paused=False, admin_paused=False)


def require_unpaused(conn, row):
    if any(pause_state(conn, row).values()):
        raise EngineError('agent_paused', 409)


def change_pause(conn, principal, agent_id, body, *, administrative=False, interface='agents'):
    principal.require('agents:write')
    if administrative and (principal.kind != 'SESSION' or not principal.admin):
        raise EngineError('administrator_session_required', 403)
    if (not isinstance(body, dict) or set(body) != {'paused', 'expected_revision', 'operation_id'}
            or type(body['paused']) is not bool or type(body['expected_revision']) is not int or body['expected_revision'] < 1):
        raise EngineError('invalid_contract')
    try:
        if str(UUID(body['operation_id'])) != body['operation_id']:raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise EngineError('invalid_operation_id') from None
    scoped = principal
    if administrative:
        owner = conn.execute(select(m.agents.c.owner_id).where(m.agents.c.id == agent_id)).scalar_one_or_none()
        if owner is None:raise EngineError('agent_not_found', 404)
        scoped = replace(principal, owner_id=owner, all_agents=True, agent_ids=frozenset())
    row = locked_agent(conn, scoped, agent_id)
    identity = dict(paused=body['paused'], expected_revision=body['expected_revision'], administrative=administrative,
                    actor_id=principal.actor_id, actor_type=principal.kind, interface=interface)
    previous = conn.execute(select(m.agent_events.c.details).where(
        m.agent_events.c.owner_id == row['owner_id'], m.agent_events.c.agent_id == agent_id,
        m.agent_events.c.action == ACTION)).scalars()
    for event in previous:
        if event.get('operation_id') == body['operation_id']:
            if event.get('request') != identity:raise EngineError('idempotency_conflict', 409)
            return row
    current = pause_state(conn, row)
    if not administrative and not body['paused'] and current['admin_paused']:
        raise EngineError('administrator_pause_active', 403)
    if row['revision'] != body['expected_revision']:
        raise EngineError('revision_conflict', 409)
    current['admin_paused' if administrative else 'user_paused'] = body['paused']
    now = now_utc()
    changed = conn.execute(update(m.agents).where(m.agents.c.id == agent_id,
        m.agents.c.owner_id == row['owner_id'], m.agents.c.revision == row['revision']).values(
            revision=row['revision']+1, updated_at=now)).rowcount
    if changed != 1:raise EngineError('revision_conflict', 409)
    row = locked_agent(conn, scoped, agent_id)
    audit_agent(conn, principal, row, ACTION, {**current, 'operation_id':body['operation_id'], 'request':identity}, now)
    return row


@api.post('/agents/<agent_id>/pause')
@endpoint('agents:write', write=True)
def owner_pause(conn, principal, repo, agent_id):
    arguments();engine_write(principal)
    row = change_pause(conn, principal, identifier(agent_id), json_body())
    return {'agent':repo.public_agent(row), 'execution_enabled':False}


@api.post('/admin/agents/<agent_id>/pause')
@endpoint(admin_only=True, write=True)
def admin_pause(conn, principal, repo, agent_id):
    arguments();engine_write(principal)
    row = change_pause(conn, principal, identifier(agent_id), json_body(), administrative=True, interface='agents-admin')
    return {'agent':repo.public_agent(row), 'execution_enabled':False}


@api.post('/internal/pwa-pause')
def pwa_pause():
    from .pwa_activation import verify_hmac
    verify_hmac(PATH);arguments();body=json_body()
    if (set(body) != {'owner_id', 'source_agent_id', 'agent_id', 'command'} or
            any(type(body[k]) is not int or body[k]<1 for k in ('owner_id','source_agent_id'))):
        raise EngineError('invalid_contract')
    with engine().begin() as conn:
        active_user(conn, body['owner_id'])
        principal=Principal(body['owner_id'],'PWA_SERVICE',str(body['owner_id']),frozenset({'agents:write'}),True,frozenset())
        row=locked_agent(conn,principal,identifier(body['agent_id']))
        if row['legacy_agent_id'] != body['source_agent_id']:raise EngineError('source_agent_mismatch',403)
        if body['command'] is not None:row=change_pause(conn,principal,row['id'],body['command'],interface='b2b')
        agent=ReadRepository(conn,principal).public_agent(row)
    return dict(api_version='agents.v1',agent=agent,owner_id=body['owner_id'],source_agent_id=body['source_agent_id'],execution_enabled=False)
