"""Central admin-only conversion policy in the existing integration settings store."""
from uuid import uuid4
from flask import request
from sqlalchemy import select, insert, update
from .api import api, endpoint, arguments, json_body
from .auth import now_utc, require_session_write
from .integration_models import integrations, audit
from .video_costs import positive
from .errors import EngineError

KEY='video-cost-policy'


@api.route('/admin/shared-video-provider', methods=['GET','PUT'])
@endpoint(admin_only=True, write=True)
def shared_video_provider(conn, principal, repo):
    from .shared_video_provider import KEY as shared_key
    from .rest_providers.models import providers
    from model.usuario import Usuario
    arguments()
    if request.method=='GET':
        row=conn.execute(select(integrations).where(integrations.c.id==shared_key)).mappings().first()
        return {'config':row['config'] if row else None,'revision':row['revision'] if row else 0}
    require_session_write(principal,'manage-integrations')
    body=json_body()
    if (not isinstance(body,dict) or set(body)!={'expected_revision','provider_id','access'}
            or type(body['expected_revision']) is not int or not isinstance(body['provider_id'],str)
            or body['access']!='all_active_users'):
        raise EngineError('invalid_contract')
    conn.execute(select(Usuario.id).where(Usuario.id==principal.owner_id).with_for_update()).first()
    provider=conn.execute(select(providers).where(providers.c.id==body['provider_id'],
        providers.c.owner_id==principal.owner_id,providers.c.adapter=='heygen',providers.c.enabled.is_(True))).mappings().first()
    if not provider or not provider['credential_ciphertext'] or provider['health']!='HEALTHY':
        raise EngineError('rest_provider_not_ready',409)
    row=conn.execute(select(integrations).where(integrations.c.id==shared_key).with_for_update()).mappings().first()
    revision=row['revision'] if row else 0
    if body['expected_revision']!=revision:raise EngineError('revision_conflict',409)
    config={'provider_id':provider['id'],'provider_owner_id':principal.owner_id,'access':'all_active_users'}
    values=dict(config=config,credential_ciphertext=None,enabled=True,revision=revision+1,diagnostic={},updated_at=now_utc())
    if row:conn.execute(update(integrations).where(integrations.c.id==shared_key).values(**values))
    else:conn.execute(insert(integrations).values(id=shared_key,**values))
    conn.execute(insert(audit).values(id=str(uuid4()),integration_id=shared_key,actor_id=principal.actor_id,
        action='SHARED_VIDEO_PROVIDER_UPDATED',revision=revision+1,created_at=now_utc()))
    return {'config':config,'revision':revision+1}


@api.get('/admin/heygen-usage')
@endpoint(admin_only=True)
def heygen_usage(conn, principal, repo):
    """Read the centrally configured HeyGen account; never expose credentials."""
    import json
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal, InvalidOperation
    from flask import current_app
    from .rest_providers.models import providers
    from .rest_providers.service import Service
    arguments()
    from .shared_video_provider import resolve_shared, resolve
    try:row=resolve_shared(conn,principal.owner_id)
    except EngineError as error:
        if error.code!='VIDEO_PROVIDER_SELECTION_REQUIRED':raise
        row=resolve(conn,principal.owner_id)
    if not row['credential_ciphertext'] or row['credential_origin']!=row['base_url'] or row['health']!='HEALTHY':
        raise EngineError('rest_provider_not_ready',409)
    service=Service(conn.engine,current_app.config)
    try:secret=json.loads(service.secrets.decrypt(row))
    except (ValueError,TypeError):raise EngineError('integration_encryption_unavailable',503) from None
    if not isinstance(secret,str) or not secret:raise EngineError('integration_encryption_unavailable',503)
    status,data=service.http.get(row['base_url'],'/v3/users/me',secret,'X-Api-Key',row['timeout_seconds'])
    if status!=200 or not isinstance(data.get('data'),dict):raise EngineError('rest_upstream_error',502)
    wallet=data['data'].get('wallet') or {};balance=wallet.get('remaining_balance');currency=wallet.get('currency')
    try:
        if isinstance(balance,bool) or balance is None:raise InvalidOperation()
        value=Decimal(str(balance))
        if not value.is_finite() or value<0:raise InvalidOperation()
        balance=str(value)
    except (InvalidOperation,ValueError,TypeError):balance=None
    if not isinstance(currency,str) or len(currency)>8:currency=None
    end=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    start=end-timedelta(days=30)
    status,usage=service.http.get(row['base_url'],'/v3/usage',secret,'X-Api-Key',row['timeout_seconds'],params={
        'start_time':int(start.timestamp()),'end_time':int(end.timestamp()),'group_by':'product','limit':100})
    items=[]
    if status==200 and isinstance(usage.get('data'),list):
        for group in usage['data']:
            if not isinstance(group,dict):continue
            for pool in group.get('pools',[]):
                if not isinstance(pool,dict):continue
                item=({key:pool.get(key) for key in ('pool','unit','charged','refunded','charge_count')} |
                    {'product':group.get('label') or group.get('tag')})
                items.append({key:value.replace(secret,'[redacted]') if isinstance(value,str) else value
                              for key,value in item.items() if value is None or isinstance(value,(str,int,float))})
    username=data['data'].get('username')
    if not isinstance(username,str) or not username or secret in username:username=None
    return {'balance':balance,'currency':currency,'connection':{'id':row['id'],'revision':row['revision'],'account_id':username},
            'usage_available':status==200 and isinstance(usage.get('data'),list),
            'usage':items,'has_more':bool(usage.get('has_more')) if status==200 else False,
            'start':start.isoformat(),'end':end.isoformat()}


@api.route('/admin/video-operations', methods=['GET','PUT'])
@endpoint(admin_only=True, write=True)
def video_operations(conn, principal, repo):
    from .video_operations import KEY as operation_key, DEFAULTS, load as load_operations
    arguments()
    if request.method == 'GET':
        switches, revision = load_operations(conn)
        return {'operations': switches, 'revision': revision}
    require_session_write(principal, 'manage-integrations')
    body = json_body()
    if (not isinstance(body, dict) or set(body) != {'expected_revision', 'operations'}
            or type(body['expected_revision']) is not int or not isinstance(body['operations'], dict)
            or set(body['operations']) != set(DEFAULTS)
            or any(type(value) is not bool for value in body['operations'].values())):
        raise EngineError('invalid_contract')
    from model.usuario import Usuario
    conn.execute(select(Usuario.id).where(Usuario.id == principal.owner_id).with_for_update()).first()
    row = conn.execute(select(integrations).where(integrations.c.id == operation_key).with_for_update()).mappings().first()
    revision = row['revision'] if row else 0
    if body['expected_revision'] != revision:
        raise EngineError('revision_conflict', 409)
    values = dict(config=body['operations'], credential_ciphertext=None, enabled=True,
                  revision=revision+1, diagnostic={}, updated_at=now_utc())
    if row:
        conn.execute(update(integrations).where(integrations.c.id == operation_key).values(**values))
    else:
        conn.execute(insert(integrations).values(id=operation_key, **values))
    conn.execute(insert(audit).values(id=str(uuid4()), integration_id=operation_key,
        actor_id=principal.actor_id, action='VIDEO_OPERATIONS_UPDATED', revision=revision+1, created_at=now_utc()))
    return {'operations': body['operations'], 'revision': revision+1}


def load(conn):
    row=conn.execute(select(integrations).where(integrations.c.id==KEY)).mappings().first()
    return {'usd_per_credit':row['config'].get('usd_per_credit') if row else None,
            'revision':row['revision'] if row else 0,
            'heygen_tariffs':row['config'].get('heygen_tariffs',[]) if row else []}


@api.route('/admin/video-cost-policy', methods=['GET','PUT'])
@endpoint(admin_only=True, write=True)
def video_cost_policy(conn, principal, repo):
    arguments()
    if request.method=='GET':return {'policy':load(conn)}
    require_session_write(principal,'manage-integrations')
    body=json_body()
    if (not isinstance(body,dict) or not {'expected_revision','usd_per_credit'}<=set(body) or set(body)-{'expected_revision','usd_per_credit','heygen_tariffs'}
            or type(body['expected_revision']) is not int):raise EngineError('invalid_contract')
    # Lock the existing owner row as well, including the first insert case.
    from model.usuario import Usuario
    conn.execute(select(Usuario.id).where(Usuario.id==principal.owner_id).with_for_update()).first()
    row=conn.execute(select(integrations).where(integrations.c.id==KEY).with_for_update()).mappings().first()
    revision=row['revision'] if row else 0
    if body['expected_revision']!=revision:raise EngineError('revision_conflict',409)
    rate=None if body['usd_per_credit'] is None else str(positive(body['usd_per_credit'],'VIDEO_COST_RATE_NOT_CONFIGURED'))
    from .video_estimates import validate_tariffs
    tariffs=validate_tariffs(body.get('heygen_tariffs',row['config'].get('heygen_tariffs',[]) if row else []))
    values=dict(config={'usd_per_credit':rate,'heygen_tariffs':tariffs},credential_ciphertext=None,enabled=rate is not None,
                revision=revision+1,diagnostic={},updated_at=now_utc())
    if row:conn.execute(update(integrations).where(integrations.c.id==KEY).values(**values))
    else:conn.execute(insert(integrations).values(id=KEY,**values))
    conn.execute(insert(audit).values(id=str(uuid4()),integration_id=KEY,actor_id=principal.actor_id,
        action='VIDEO_COST_POLICY_UPDATED',revision=revision+1,created_at=now_utc()))
    return {'policy':load(conn)}


@api.post('/admin/jobs/<job_id>/video-cost-reconciliation')
@endpoint(admin_only=True,write=True)
def reconcile_video_cost(conn,principal,repo,job_id):
    from .api import identifier
    from . import models as m
    from .video_costs import reconcile
    from .result_consolidation import consolidate
    from .management import audit_agent
    from urllib.parse import urlsplit
    arguments();require_session_write(principal,'manage-integrations')
    body=json_body()
    if (not isinstance(body,dict) or set(body)!={'result_id','remote_id','actual_usd','reference'}
            or not all(isinstance(body[k],str) for k in body)):
        raise EngineError('invalid_contract')
    ref=urlsplit(body['reference'])
    if ref.scheme!='https' or not ref.hostname or ref.username or ref.password or ref.query or ref.fragment or len(body['reference'])>2000:
        raise EngineError('invalid_contract')
    job=conn.execute(select(m.jobs).where(m.jobs.c.id==identifier(job_id)).with_for_update()).mappings().first()
    if not job:raise EngineError('job_not_found',404)
    task=conn.execute(select(m.tasks).where(m.tasks.c.job_id==job['id'],m.tasks.c.owner_id==job['owner_id'],
        m.tasks.c.tool_id=='dpia.video.produce',m.tasks.c.state=='COMPLETED').with_for_update()).mappings().first()
    result=conn.execute(select(m.results).where(m.results.c.job_id==job['id'],m.results.c.owner_id==job['owner_id']).order_by(m.results.c.version.desc()).limit(1).with_for_update()).mappings().first()
    if not task or not result or result['id']!=body['result_id']:raise EngineError('revision_conflict',409)
    output=dict(task['output']);video=dict(output.get('video') or {})
    if video.get('remote_id')!=body['remote_id']:raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
    old=video['cost']
    if old.get('reconciliation')=='CONFIRMED':
        if old.get('actual_usd')!=body['actual_usd'] or old.get('confirmation_reference')!=body['reference']:
            raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
        return {'cost':old}
    settled=reconcile(conn,job['owner_id'],old,body['actual_usd'],now_utc())
    video['cost']={**old,**settled,'reconciliation':'CONFIRMED',
        'confirmation_source':'ADMIN_PROVIDER_DOCUMENT','confirmation_reference':body['reference']}
    output['video']=video
    conn.execute(update(m.tasks).where(m.tasks.c.id==task['id'],m.tasks.c.owner_id==job['owner_id']).values(output=output))
    outputs=conn.execute(select(m.tasks.c.output).where(m.tasks.c.job_id==job['id'],m.tasks.c.owner_id==job['owner_id'],m.tasks.c.state=='COMPLETED').order_by(m.tasks.c.position)).scalars().all()
    canonical=consolidate(outputs)
    conn.execute(update(m.results).where(m.results.c.id==result['id'],m.results.c.owner_id==job['owner_id']).values(payload=canonical))
    agent=conn.execute(select(m.agents).where(m.agents.c.id==job['agent_id'],m.agents.c.owner_id==job['owner_id'])).mappings().one()
    audit_agent(conn,principal,agent,'VIDEO_COST_RECONCILED',{'job_id':job['id'],'result_id':result['id'],
        'remote_id':body['remote_id'],'confirmation_reference':body['reference']},now_utc())
    return {'cost':video['cost']}
