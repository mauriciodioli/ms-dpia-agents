"""Opaque client credentials: random 256-bit secrets, SHA-256 at rest.

Provider secrets are never accepted here. A supplied invalid Bearer token never
falls back to a cookie session. API clients cannot gain administrator privileges.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from hmac import compare_digest
import re
import secrets
from uuid import UUID, uuid4
from flask import request, session
from sqlalchemy import select, insert, update
from model.usuario import Usuario
from .contracts import SCOPES, CLIENT_CREATE, validate, utc, iso
from .errors import EngineError
from .models import agents, clients, client_grants, security_events

TOKEN = re.compile(r'^dpa_([0-9a-f]{32})\.([A-Za-z0-9_-]{43})$')
ADMIN_ROLES = frozenset({'admin', 'administrador'})


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Principal:
    owner_id: int
    kind: str
    actor_id: str
    scopes: frozenset[str]
    all_agents: bool
    agent_ids: frozenset[str]
    admin: bool = False

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise EngineError('insufficient_scope', 403)


def active_user(conn, user_id: int):
    if type(user_id) is not int or user_id <= 0:
        raise EngineError('authentication_required', 401)
    row = conn.execute(select(Usuario.id, Usuario.roll).where(
        Usuario.id == user_id, Usuario.activo.is_(True))).mappings().first()
    if row is None:
        raise EngineError('authentication_required', 401)
    return row


def authenticate(conn, *, admin_only: bool = False, now: datetime | None = None) -> Principal:
    now = now or now_utc()
    header = request.headers.get('Authorization')
    if header is not None:
        if admin_only:
            raise EngineError('administrator_session_required', 403)
        parts = header.split(' ')
        match = TOKEN.fullmatch(parts[1]) if len(parts) == 2 and parts[0].lower() == 'bearer' else None
        if match is None:
            raise EngineError('invalid_client_credentials', 401)
        client_id = str(UUID(hex=match.group(1)))
        row = conn.execute(select(clients).where(clients.c.id == client_id)).mappings().first()
        digest = sha256(parts[1].encode('ascii')).hexdigest()
        if (row is None or not compare_digest(row['token_digest'], digest) or row['revoked_at'] is not None
                or row['expires_at'] <= now):
            raise EngineError('invalid_client_credentials', 401)
        active_user(conn, row['owner_id'])
        if (not isinstance(row['scopes'], list) or not row['scopes'] or
                any(not isinstance(scope, str) or scope not in SCOPES for scope in row['scopes'])):
            raise EngineError('invalid_client_credentials', 401)
        grants = conn.execute(select(client_grants.c.agent_id).where(
            client_grants.c.owner_id == row['owner_id'], client_grants.c.client_id == client_id)).scalars()
        return Principal(row['owner_id'], 'API_CLIENT', client_id, frozenset(row['scopes']),
                         bool(row['all_agents']), frozenset(grants))
    user = active_user(conn, session.get('user_id'))
    is_admin = str(user['roll']).strip().casefold() in ADMIN_ROLES
    if admin_only and not is_admin:
        raise EngineError('administrator_session_required', 403)
    return Principal(user['id'], 'SESSION', str(user['id']), SCOPES, True, frozenset(), is_admin)


def require_session_write(principal: Principal, action: str = 'manage-api-clients') -> None:
    if principal.kind != 'SESSION':
        raise EngineError('session_required', 403)
    # Custom header + exact same origin; no permissive CORS is installed.
    from urllib.parse import urlsplit
    origin = request.headers.get('Origin')
    if (request.headers.get('X-DPIA-Action') != action
            or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
        raise EngineError('invalid_request_origin', 403)
    if origin:
        try:
            parsed = urlsplit(origin)
            if parsed.scheme != request.scheme or parsed.netloc != request.host or parsed.path or parsed.query or parsed.fragment:
                raise ValueError
        except ValueError:
            raise EngineError('invalid_request_origin', 403) from None


def new_token(client_id: str) -> tuple[str, str]:
    value = 'dpa_' + UUID(client_id).hex + '.' + secrets.token_urlsafe(32)
    return value, sha256(value.encode('ascii')).hexdigest()


def public_client(row) -> dict:
    return {key: row[key] for key in ('id', 'name', 'scopes', 'all_agents')} | {
        'expires_at': iso(row['expires_at']), 'revoked_at': iso(row['revoked_at'])}


def record_security_event(conn, principal, client_id, action):
    conn.execute(insert(security_events).values(id=str(uuid4()), owner_id=principal.owner_id,
        client_id=client_id, actor_id=principal.actor_id, action=action, created_at=now_utc()))


def issue_client(conn, principal: Principal, body: dict, *, now: datetime | None = None) -> dict:
    require_session_write(principal)
    validate(CLIENT_CREATE, body)
    now = now or now_utc()
    expires = utc(body['expires_at'])
    if expires <= now or expires - now > timedelta(days=366):
        raise EngineError('invalid_expiration')
    if body['agent_ids']:
        owned = conn.execute(select(agents.c.id).where(agents.c.owner_id == principal.owner_id,
            agents.c.id.in_(body['agent_ids']))).scalars().all()
        if set(owned) != set(body['agent_ids']):
            raise EngineError('agent_not_found', 404)
    client_id = str(uuid4())
    token, digest = new_token(client_id)
    row = dict(id=client_id, owner_id=principal.owner_id, name=body['name'].strip(),
               token_digest=digest, scopes=sorted(body['scopes']), all_agents=body['all_agents'],
               expires_at=expires, revoked_at=None, created_at=now)
    if not row['name']:
        raise EngineError('invalid_contract')
    conn.execute(insert(clients).values(**row))
    for agent_id in body['agent_ids']:
        conn.execute(insert(client_grants).values(owner_id=principal.owner_id, client_id=client_id, agent_id=agent_id))
    record_security_event(conn, principal, client_id, 'CLIENT_CREATED')
    return {'client': public_client(row), 'token': token, 'token_type': 'Bearer'}


def revoke_client(conn, principal: Principal, client_id: str) -> dict:
    require_session_write(principal)
    row = conn.execute(select(clients).where(clients.c.owner_id == principal.owner_id,
        clients.c.id == client_id).with_for_update()).mappings().first()
    if row is None:
        raise EngineError('client_not_found', 404)
    if row['revoked_at'] is None:
        conn.execute(update(clients).where(clients.c.id == client_id,
            clients.c.owner_id == principal.owner_id).values(revoked_at=now_utc()))
        record_security_event(conn, principal, client_id, 'CLIENT_REVOKED')
    return {'id': client_id, 'revoked': True}


def rotate_client(conn, principal: Principal, client_id: str) -> dict:
    require_session_write(principal)
    row = conn.execute(select(clients).where(clients.c.owner_id == principal.owner_id,
        clients.c.id == client_id).with_for_update()).mappings().first()
    if row is None:
        raise EngineError('client_not_found', 404)
    if row['revoked_at'] is not None or row['expires_at'] <= now_utc():
        raise EngineError('client_inactive', 409)
    token, digest = new_token(client_id)
    conn.execute(update(clients).where(clients.c.id == client_id,
        clients.c.owner_id == principal.owner_id).values(token_digest=digest))
    record_security_event(conn, principal, client_id, 'CLIENT_ROTATED')
    return {'client': public_client(row), 'token': token, 'token_type': 'Bearer'}
