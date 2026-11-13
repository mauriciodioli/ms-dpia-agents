"""Automatic access to enabled standard providers, with durable owner opt-outs.

Uses existing connections/grants/audit tables. No schema or credential changes.
Callers hold the owner/agent lock before writing, shared with explicit revocation.
"""
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select, insert, update, delete, and_
from . import models as m
from .integration_models import integrations
from .integrations import PROVIDERS
from .auth import now_utc
from .errors import EngineError


def connection_id(agent, provider):
    return str(uuid5(NAMESPACE_URL, f"agents-access:{provider}:{agent['owner_id']}:{agent['id']}"))


def revoked(conn, agent, provider):
    marker=conn.execute(select(m.connections.c.enabled).where(m.connections.c.id==connection_id(agent,provider),m.connections.c.owner_id==agent['owner_id'])).first()
    if marker is not None:return not marker.enabled
    spec=PROVIDERS[provider]
    granted=conn.execute(select(m.connections.c.enabled).join(m.tool_grants,and_(m.tool_grants.c.connection_id==m.connections.c.id,m.tool_grants.c.owner_id==m.connections.c.owner_id)).where(m.tool_grants.c.owner_id==agent['owner_id'],m.tool_grants.c.agent_id==agent['id'],m.tool_grants.c.tool_id==spec['tool'])).first()
    if granted:return not granted.enabled
    # Honor revocations made before automatic access was introduced.
    return conn.execute(select(m.agent_events.c.id).where(m.agent_events.c.owner_id==agent['owner_id'],m.agent_events.c.agent_id==agent['id'],m.agent_events.c.action=='PROVIDER_REVOKED',m.agent_events.c.details['provider'].as_string()==spec['provider']).limit(1)).first() is not None


def available(conn, provider):
    row=conn.execute(select(integrations.c.enabled,integrations.c.credential_ciphertext).where(integrations.c.id==provider)).first()
    return bool(row and row.enabled and row.credential_ciphertext)


def can_use(conn, agent, provider):
    return available(conn,provider) and not revoked(conn,agent,provider)


def set_access(conn, agent, provider, enabled):
    spec=PROVIDERS[provider];cid=connection_id(agent,provider)
    # Shared lock order: agent, then integration; serialize first-use provisioning.
    conn.execute(select(integrations.c.id).where(integrations.c.id==provider).with_for_update()).first()
    if not conn.execute(select(m.providers.c.id).where(m.providers.c.id==spec['provider'])).first():
        conn.execute(insert(m.providers).values(id=spec['provider'],kind=spec['capability'],registry_key=spec['tool'],contract_version='v1'))
    marker=conn.execute(select(m.connections.c.id).where(m.connections.c.id==cid,m.connections.c.owner_id==agent['owner_id'])).first()
    if marker:conn.execute(update(m.connections).where(m.connections.c.id==cid,m.connections.c.owner_id==agent['owner_id']).values(enabled=enabled))
    else:conn.execute(insert(m.connections).values(id=cid,owner_id=agent['owner_id'],provider_id=spec['provider'],name=provider,credential_ref='integration:'+provider,enabled=enabled,created_at=now_utc()))
    conn.execute(delete(m.tool_grants).where(m.tool_grants.c.owner_id==agent['owner_id'],m.tool_grants.c.agent_id==agent['id'],m.tool_grants.c.tool_id==spec['tool']))
    if enabled:
        cap=conn.execute(select(m.agent_capabilities.c.tool_id).where(m.agent_capabilities.c.owner_id==agent['owner_id'],m.agent_capabilities.c.agent_id==agent['id'],m.agent_capabilities.c.tool_id==spec['tool'])).first()
        if not cap:conn.execute(insert(m.agent_capabilities).values(owner_id=agent['owner_id'],agent_id=agent['id'],tool_id=spec['tool']))
        conn.execute(insert(m.tool_grants).values(owner_id=agent['owner_id'],agent_id=agent['id'],tool_id=spec['tool'],connection_id=cid))


def ensure_access(conn, agent, provider):
    if revoked(conn,agent,provider):raise EngineError('provider_access_revoked',403)
    if not available(conn,provider):return False
    spec=PROVIDERS[provider]
    existing=conn.execute(select(m.tool_grants.c.agent_id).where(m.tool_grants.c.owner_id==agent['owner_id'],m.tool_grants.c.agent_id==agent['id'],m.tool_grants.c.tool_id==spec['tool'])).first()
    cap=conn.execute(select(m.agent_capabilities.c.tool_id).where(m.agent_capabilities.c.owner_id==agent['owner_id'],m.agent_capabilities.c.agent_id==agent['id'],m.agent_capabilities.c.tool_id==spec['tool'])).first()
    if not existing or not cap:
        set_access(conn,agent,provider,True)
        from .management import audit_agent
        from .auth import Principal,SCOPES
        audit_agent(conn,Principal(agent['owner_id'],'SYSTEM','manager',SCOPES,True,frozenset()),agent,'PROVIDER_AUTO_GRANTED',{'provider':spec['provider']})
    return True
