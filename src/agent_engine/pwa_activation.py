"""Authenticated, atomic PWA provisioning. Never dispatches jobs or live schedules."""
import hashlib
import hmac
import json
import time
from flask import current_app, request
from sqlalchemy import select, update
from .api import api, engine, json_body, arguments
from .auth import active_user, Principal
from .contracts import AGENT_CREATE, SCHEDULE_CREATE, validate
from .errors import EngineError
from .management import AgentManager, audit_agent, locked_agent
from .repository import ReadRepository
from .tools import default_registry
from . import models as m

PATH = '/api/agents/v1/internal/pwa-activations'


def verify_hmac(path):
    # Separate, narrowly scoped credential. Cookies and API-client tokens cannot impersonate owners.
    key = current_app.config.get('PWA_ACTIVATION_SECRET', '')
    stamp = request.headers.get('X-DPIA-Timestamp', '')
    raw = request.get_data(cache=True) if (request.content_length or 0) <= 65536 else b''
    try:
        fresh = abs(time.time() - int(stamp)) <= 60
    except ValueError:
        fresh = False
    signature = hmac.new(key.encode(), stamp.encode()+b'\n'+path.encode()+b'\n'+raw, hashlib.sha256).hexdigest()
    if not key or not fresh or not hmac.compare_digest(signature, request.headers.get('X-DPIA-Signature', '')):
        raise EngineError('invalid_service_credentials', 401)


@api.post('/internal/pwa-activations')
def activate_pwa():
    verify_hmac(PATH)
    arguments()
    body = json_body()
    if (set(body) != {'owner_id', 'source_agent_id', 'source_revision', 'agent', 'schedule', 'preferences'}
            or any(type(body[k]) is not int or body[k] < 1 for k in ('owner_id', 'source_agent_id', 'source_revision'))):
        raise EngineError('invalid_contract')
    validate(AGENT_CREATE, body['agent'])
    validate(SCHEDULE_CREATE, body['schedule'])
    # This integration only supports product discovery, never silently substitutes monitoring tools.
    if body['agent']['capabilities'] != ['dpia.amazon.search']:
        raise EngineError('unsupported_pwa_capabilities', 422)
    default_registry().validate_agent(body['agent'])
    prefs = body['preferences']
    if (not isinstance(prefs, dict) or set(prefs) != {'points', 'period', 'notifications'}
            or type(prefs['points']) is not int or not 0 <= prefs['points'] <= 1000000
            or prefs['period'] not in ('week', 'month') or type(prefs['notifications']) is not bool):
        raise EngineError('unsupported_pwa_preferences', 422)
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    owner = body['owner_id']
    with engine().begin() as conn:
        # B2B holds the shared usuario row lock while awaiting this response.
        # Read ownership without reacquiring that lock across the HTTP boundary.
        # Existing agent locks and unique legacy_agent_id protect concurrent retries.
        active_user(conn, owner)
        from .owner_identity import owner_email
        verified_name=owner_email(conn,owner)
        deleted=conn.execute(select(m.agent_deletions.c.snapshot).where(
            m.agent_deletions.c.owner_id==owner,m.agent_deletions.c.legacy_agent_id==body['source_agent_id'])).scalars().all()
        if any(body['source_revision']<=entry.get('source_revision',0) for entry in deleted):
            raise EngineError('source_agent_deleted',409)
        principal = Principal(owner, 'PWA_SERVICE', 'ms202611sb2b', frozenset({'agents:write', 'agents:read'}), True, frozenset())
        row = conn.execute(select(m.agents).where(m.agents.c.legacy_agent_id == body['source_agent_id']).with_for_update()).mappings().first()
        if row:
            if row['owner_id'] != owner:
                raise EngineError('source_owner_conflict', 409)
            event = conn.execute(select(m.agent_events.c.details).where(m.agent_events.c.owner_id == owner,
                m.agent_events.c.agent_id == row['id'], m.agent_events.c.action == 'PWA_ACTIVATED')).scalar_one_or_none()
            if not event or event.get('fingerprint') != fingerprint or row['configuration_state'] != 'ENABLED':
                raise EngineError('source_configuration_conflict', 409)
            # Do not reactivate an independently edited agent on a stale replay.
            if event.get('engine_revision') != row['revision']:
                changes=conn.execute(select(m.agent_events.c.action,m.agent_events.c.revision).where(
                    m.agent_events.c.owner_id==owner,m.agent_events.c.agent_id==row['id'],
                    m.agent_events.c.revision>event['engine_revision'])).all()
                if (len(changes)!=row['revision']-event['engine_revision'] or
                        any(change.action!='AGENT_PAUSE_CHANGED' for change in changes)):
                    raise EngineError('source_configuration_conflict',409)
        else:
            manager = AgentManager(conn, principal)
            created = manager.save({**body['agent'],'name':verified_name})
            conn.execute(update(m.agents).where(m.agents.c.id == created['id']).values(legacy_agent_id=body['source_agent_id']))
            manager.set_enabled(created['id'], {'expected_revision': created['revision']}, True)
            row = locked_agent(conn, principal, created['id'])
            # Schedule and budget preferences remain dormant: activation grants no execution authorization.
            audit_agent(conn, principal, row, 'PWA_ACTIVATED', {'fingerprint': fingerprint,
                'engine_revision': row['revision'], 'source_revision': body['source_revision'],
                'schedule': body['schedule'], 'preferences': prefs, 'execution_enabled': False})
        if row['name']!=verified_name:
            conn.execute(update(m.agents).where(m.agents.c.id==row['id'],m.agents.c.owner_id==owner).values(name=verified_name))
            row={**row,'name':verified_name}
        agent = ReadRepository(conn, principal).public_agent(row, configuration=True)
    return {'api_version': 'agents.v1', 'agent': agent, 'owner_id': owner,
            'source_agent_id': body['source_agent_id'], 'source_revision': body['source_revision'],
            'execution_enabled': False}, 200
