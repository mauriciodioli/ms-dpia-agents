"""Authenticated, atomic PWA provisioning. Never dispatches jobs or live schedules."""
import hashlib
import hmac
import json
import time
from flask import current_app, request
from sqlalchemy import select, update, insert
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
    if body.get('operation') in ('video_resources','video_quote'):
        return video_resources_catalog(body)
    if body.get('operation') in ('schedule_task_now','run_existing_task_now'):
        from .immediate_tasks import schedule_now
        with engine().begin() as conn:
            return schedule_now(conn,body),200
    if body.get('operation') == 'task_sources':
        return task_sources_catalog(body)
    if body.get('operation') in ('sync_task_schedule','update_task_schedule'):
        return synchronize_task_schedule(body)
    if (set(body) != {'owner_id', 'source_agent_id', 'source_revision', 'agent', 'schedule', 'preferences'}
            or any(type(body[k]) is not int or body[k] < 1 for k in ('owner_id', 'source_agent_id', 'source_revision'))):
        raise EngineError('invalid_contract')
    validate(AGENT_CREATE, body['agent'])
    validate(SCHEDULE_CREATE, body['schedule'])
    # This integration only supports product discovery, never silently substitutes monitoring tools.
    if body['agent']['capabilities'] not in (['dpia.amazon.search'], ['dpia.amazon.search', 'openai.analysis']):
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
        from .configured_task_repository import ConfiguredTaskRepository
        from .task_schedules import synchronize
        legacy_tasks=ConfiguredTaskRepository(conn).rows(row)
        for task in legacy_tasks:
            if not (task['parametros'] or {}).get('_deleted_at'):
                synchronize(conn,principal,row,task['id'],default_schedule=body['schedule'])
        if row['name']!=verified_name:
            conn.execute(update(m.agents).where(m.agents.c.id==row['id'],m.agents.c.owner_id==owner).values(name=verified_name))
            row={**row,'name':verified_name}
        agent = ReadRepository(conn, principal).public_agent(row, configuration=True)
    return {'api_version': 'agents.v1', 'agent': agent, 'owner_id': owner,
            'source_agent_id': body['source_agent_id'], 'source_revision': body['source_revision'],
            'execution_enabled': False}, 200


def video_resources_catalog(body):
    quoting = body['operation']=='video_quote'
    fields={'operation','owner_id','source_agent_id','task_id','language'}
    if quoting: fields.update(('duration','format','avatar_id','voice_id'))
    if (set(body)!=fields or
            any(type(body.get(k)) is not int or body[k]<1 for k in ('owner_id','source_agent_id','task_id')) or
            not isinstance(body.get('language'),str)):
        raise EngineError('invalid_contract',422)
    from .configured_task_repository import ConfiguredTaskRepository
    from .shared_video_provider import resolve
    from .rest_providers.api import service
    from .contracts import SCOPES
    with engine().connect() as conn:
        owner=body['owner_id'];active_user(conn,owner)
        agent=conn.execute(select(m.agents).where(m.agents.c.owner_id==owner,
            m.agents.c.legacy_agent_id==body['source_agent_id'])).mappings().first()
        repository = ConfiguredTaskRepository(conn)
        if agent:
            rows = repository.rows(agent,body['task_id'])
        else:
            # Catalog lookup requires an owned configured task, but it need not
            # create a scheduler entry or provision a job just to list resources.
            from sqlalchemy import MetaData, Table
            legacy = Table('agentes', MetaData(), autoload_with=conn, resolve_fks=False)
            tasks = repository.table()
            rows = conn.execute(select(tasks).join(legacy, tasks.c.agente_id == legacy.c.id).where(
                legacy.c.id == body['source_agent_id'], legacy.c.usuario_id == owner,
                tasks.c.id == body['task_id'],
            )).mappings().all()
        if not rows or rows[0]['tipo']!='VIDEO_GENERAR' or (rows[0]['parametros'] or {}).get('_deleted_at'):
            raise EngineError('task_not_found',404)
        provider=resolve(conn,owner)
        if quoting:
            if (type(body['duration']) is not int or body['duration'] not in (15,30,60)
                or body['format'] not in ('16:9','9:16','1:1')
                or body['language'] not in ('es','en','it')
                or any(not isinstance(body[k],str) or not 0<len(body[k])<=256 for k in ('avatar_id','voice_id'))):
                raise EngineError('invalid_contract',422)
    if quoting:
        return quote_video(body),200
    principal=Principal(owner,'PWA_SERVICE','ms202611sb2b',SCOPES,True,frozenset())
    return service().video_resources(principal,provider['id'],body['language'],configured_task=True),200


def synchronize_task_schedule(body):
    updating=body['operation']=='update_task_schedule'
    if (set(body)!=({'operation','owner_id','source_agent_id','task_id','schedule'} if updating else {'operation','owner_id','source_agent_id','task_id'}) or
            any(type(body[key]) is not int or body[key]<1 for key in ('owner_id','source_agent_id','task_id'))):
        raise EngineError('invalid_contract')
    with engine().begin() as conn:
        active_user(conn,body['owner_id'])
        principal=Principal(body['owner_id'],'PWA_SERVICE','ms202611sb2b',frozenset({'agents:read','agents:write','jobs:create','mcp:execute'}),True,frozenset())
        if updating:
            from .configured_task_repository import ConfiguredTaskRepository
            ConfiguredTaskRepository(conn).lock_owner(body['owner_id'])
        row=conn.execute(select(m.agents).where(m.agents.c.owner_id==body['owner_id'],
            m.agents.c.legacy_agent_id==body['source_agent_id']).with_for_update()).mappings().first()
        if row is None:raise EngineError('agent_not_found',404)
        row=locked_agent(conn,principal,row['id'])
        from .task_schedules import synchronize
        if updating:
            from .configured_tasks import ConfiguredTaskManager
            saved=ConfiguredTaskManager(conn,principal).update_schedule(row['id'],body['task_id'],body['schedule'])
            schedule=saved['schedules'][0]
        else:
            schedule=synchronize(conn,principal,row,body['task_id'])
    return {'api_version':'agents.v1','owner_id':body['owner_id'],'source_agent_id':body['source_agent_id'],
            'task_id':body['task_id'],'schedule':schedule,'execution_enabled':False},200


def task_sources_catalog(body):
    if set(body) != {'operation', 'owner_id'} or type(body['owner_id']) is not int or body['owner_id'] < 1:
        raise EngineError('invalid_contract')
    with engine().connect() as conn:
        active_user(conn, body['owner_id'])
        agent = conn.execute(select(m.agents).where(m.agents.c.owner_id == body['owner_id'],
            ~select(m.agent_deletions.c.agent_id).where(m.agent_deletions.c.agent_id == m.agents.c.id).exists())
            .order_by(m.agents.c.legacy_agent_id.is_(None), m.agents.c.created_at.desc()).limit(1)).mappings().first()
        # Before first provisioning, display the central available catalog only.
        if agent is None:
            agent = {'owner_id':body['owner_id'], 'id':'00000000-0000-0000-0000-000000000000'}
        from .task_sources import catalog
        items = catalog(conn, agent, default_registry(conn=conn, owner=body['owner_id']))
    return {'api_version':'agents.v1', 'owner_id':body['owner_id'], 'items':items}, 200


def quote_video(body):
    import json
    from decimal import Decimal, ROUND_CEILING
    from flask import current_app
    from .video_worker import VideoHandlers, voice_settings
    from .heygen_resources import resolve_resource
    from .video_estimates import estimate
    from .video_cost_api import load
    from .video_costs import positive
    from .auth import now_utc
    handler=VideoHandlers(engine(),current_app.config)
    with engine().connect() as conn:
        row=handler.provider(conn,body['owner_id'])
    try: secret=json.loads(handler.rest.secrets.decrypt(row))
    except (ValueError,TypeError): raise EngineError('integration_encryption_unavailable',503) from None
    if not isinstance(secret,str) or not secret: raise EngineError('integration_encryption_unavailable',503)
    read=lambda path,params=None:handler.request(row,secret,path,params,full=True)
    avatar,ar=resolve_resource(read,'avatar_id',body['avatar_id'],body['language'])
    voice,vr=resolve_resource(read,'voice_id',body['voice_id'],body['language'])
    settings=voice_settings(handler.request(row,secret,'/v3/videos/voice-capabilities'),body['language'])
    if vr.get('mode')=='professional': settings['engine_settings'].pop('model',None)
    request_body={'avatar_id':avatar,'voice_id':voice,'aspect_ratio':body['format'],
                  'engine':{'type':'avatar_iv'},'resolution':'720p','voice_settings':settings}
    account=handler.request(row,secret,'/v3/users/me')
    with engine().begin() as conn:
        current=handler.provider(conn,body['owner_id'])
        if current['id']!=row['id'] or current['revision']!=row['revision']:
            raise EngineError('VIDEO_CONFIGURATION_CHANGED',409)
        rate=positive(load(conn)['usd_per_credit'],'VIDEO_COST_RATE_NOT_CONFIGURED')
        quote=estimate(conn,row,request_body,body['duration'],now_utc(),account,
                       avatar_type=ar.get('avatar_type'),voice_mode=vr.get('mode'),check_balance=False)
        credits=int((Decimal(quote['estimated_usd'])/rate).to_integral_value(rounding=ROUND_CEILING))
    return {'currency':'USD','estimated_usd':quote['estimated_usd'],'amount':str(credits*rate),
            'usd_per_credit':str(rate),'required_credits':credits,'valid_until':quote['valid_until'],
            'provisional':quote['provisional'],'policy_revision':quote['policy_revision']}
