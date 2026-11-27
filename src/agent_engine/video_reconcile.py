"""Recover a timed-out submitted video without submitting another production."""
import json
import re
from urllib.parse import urlsplit
from sqlalchemy import select, update, insert
from . import models as m
from .errors import EngineError
from .rest_providers.models import providers
from .rest_providers.service import Service
from .video_worker import prior_script


def validate_reservation(conn,job,task,*,lock=False):
    from uuid import UUID,uuid5,NAMESPACE_URL
    from services.scraping_quota import operaciones
    from services.agent_point_status import context
    reservation=(task['output'] or {}).get('reservation') or {}
    operation=reservation.get('operation');units=reservation.get('reserved_credits')
    try:
        if str(UUID(operation))!=operation or type(units) is not int or not 1<=units<=1000:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise EngineError('VIDEO_RESERVATION_CONFLICT',409) from None
    ids=[str(uuid5(NAMESPACE_URL,operation+':'+str(i))) for i in range(units)]
    query=select(operaciones).where(operaciones.c.usuario_id==job['owner_id'],operaciones.c.operacion_id.in_(ids))
    holds=conn.execute(query.with_for_update() if lock else query).mappings().all()
    if len(holds)!=units or any(r['estado'] not in ('reserved','dispatching','pending') or context(r).get('job_id')!=job['id'] or context(r).get('task_id')!=task['id'] or context(r).get('video_operation')!=operation for r in holds):
        raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
    return reservation


def inspect_video(engine, config, job_id, *, service=None, _internal=False):
    from uuid import UUID
    try:
        if str(UUID(job_id)) != job_id: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise EngineError('invalid_job_id', 422) from None
    with engine.connect() as conn:
        job=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id)).mappings().first()
        if not job: raise EngineError('job_not_found',404)
        from .auth import active_user
        active_user(conn,job['owner_id'])
        if job['state']!='FAILED' or job['error_code']!='JOB_DEADLINE_EXCEEDED':
            raise EngineError('video_reconciliation_not_eligible',409)
        tasks=conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
            m.tasks.c.job_id==job_id).order_by(m.tasks.c.position)).mappings().all()
        if len(tasks)!=2 or [t['tool_id'] for t in tasks]!=['dpia.video.script','dpia.video.produce']:
            raise EngineError('video_reconciliation_not_eligible',409)
        script,task=tasks
        if script['state']!='COMPLETED' or task['state']!='FAILED' or task['provider_submission_state']!='SUBMITTED':
            raise EngineError('video_reconciliation_not_eligible',409)
        remote=task['provider_job_id']; checkpoint=task['output'] or {}
        if not isinstance(remote,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',remote):
            raise EngineError('video_reconciliation_not_eligible',409)
        if not isinstance(checkpoint,dict) or checkpoint.get('remote_id')!=remote or not isinstance(checkpoint.get('reservation'),dict):
            raise EngineError('video_reconciliation_checkpoint_missing',409)
        script_value=prior_script([script['output'] or {}])
        validate_reservation(conn,job,task)
        if conn.execute(select(m.results.c.id).where(m.results.c.owner_id==job['owner_id'],m.results.c.job_id==job_id)).first() or conn.execute(select(m.deliveries.c.id).where(m.deliveries.c.owner_id==job['owner_id'],m.deliveries.c.job_id==job_id)).first():
            raise EngineError('video_reconciliation_result_exists',409)
        provider=conn.execute(select(providers).where(providers.c.id==checkpoint.get('provider_id'),
            providers.c.adapter=='heygen')).mappings().first()
        if (not provider or provider['revision']!=checkpoint.get('provider_revision')
                or not provider['credential_ciphertext'] or provider['credential_origin']!=provider['base_url']):
            raise EngineError('video_reconciliation_provider_changed',409)
        from .shared_video_provider import resolve
        current_provider=resolve(conn,job['owner_id'])
        if current_provider['id']!=provider['id'] or current_provider['owner_id']!=provider['owner_id']:
            raise EngineError('video_reconciliation_provider_changed',409)
        agent=conn.execute(select(m.agents).where(m.agents.c.id==job['agent_id'],m.agents.c.owner_id==job['owner_id'])).mappings().first()
        if not agent or not job['legacy_task_id']:
            raise EngineError('VIDEO_TASK_NOT_AUTHORIZED',403)
        from .configured_task_repository import ConfiguredTaskRepository
        configured=ConfiguredTaskRepository(conn).rows(agent,job['legacy_task_id'])
        if not configured or configured[0]['tipo']!='VIDEO_GENERAR':
            raise EngineError('VIDEO_TASK_NOT_AUTHORIZED',403)
        provider=dict(provider)
    service=service or Service(engine,config)
    try: secret=json.loads(service.secrets.decrypt(provider))
    except (ValueError,TypeError): raise EngineError('integration_encryption_unavailable',503) from None
    if not isinstance(secret,str) or not secret: raise EngineError('integration_encryption_unavailable',503)
    status,data=service.http.get(provider['base_url'],'/v3/videos/'+remote,secret,'X-Api-Key',provider['timeout_seconds'])
    value=data.get('data') if isinstance(data,dict) else None
    if status!=200 or not isinstance(value,dict) or value.get('id')!=remote:
        raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
    state=value.get('status')
    if state not in ('waiting','pending','processing','completed','failed','error'):
        raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
    valid_url=False
    if state=='completed':
        url=value.get('video_url'); parsed=urlsplit(url) if isinstance(url,str) else None
        valid_url=bool(parsed and parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password and secret not in url)
        if not valid_url: raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
    report={'job_id':job_id,'provider_status':state,'video_url_available':valid_url,
            'eligible':state=='completed','mode':'dry-run'}
    if _internal and valid_url:
        return report,{'job':dict(job),'task':dict(task),'script_task':dict(script),
            'script':script_value,'checkpoint':checkpoint,'provider':provider,'url':url,'provider_result':value}
    return (report,None) if _internal else report


def recover_video(engine, config, job_id, *, service=None, apply=False, now=None):
    from uuid import uuid4
    from .auth import now_utc
    from .state_store import reopen_timed_out_video
    from .video_worker import encoded_result
    from .video_costs import measured_duration, transition
    from .execution_manager import ExecutionManager
    from .task_box import TaskBox
    from .informational_delivery import eligible_result, REASON
    from .dispatcher import Dispatcher
    from .configured_task_repository import ConfiguredTaskRepository
    from .tools import default_registry
    now=now or now_utc()
    with engine.connect() as conn:
        existing=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id)).mappings().first()
        if existing and (existing['configuration_snapshot'] or {}).get('video_recovery',{}).get('completed'):
            return {'job_id':job_id,'state':existing['state'],'already_recovered':True,'mode':'apply' if apply else 'dry-run'}
    try:report,data=inspect_video(engine,config,job_id,service=service,_internal=True)
    except EngineError as error:
        if error.code!='video_reconciliation_not_eligible':raise
        with engine.connect() as conn:
            latest=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id)).mappings().first()
            if latest and (latest['configuration_snapshot'] or {}).get('video_recovery',{}).get('completed'):
                return {'job_id':job_id,'state':latest['state'],'already_recovered':True,'mode':'apply' if apply else 'dry-run'}
        raise
    if not data:return report
    if not apply:return report
    old=data['job']; task=data['task']; reservation=data['checkpoint']['reservation']
    duration = measured_duration(data['provider_result'])
    duration_evidence = ({'delivered_seconds': duration,
                          'duration_source': 'HEYGEN_VIDEO_RESPONSE'} if duration else {})
    video={'url':data['url'],'provider':'heygen','remote_id':task['provider_job_id'],'state':'COMPLETED',
        'script':data['script'],'cost':{**reservation,**duration_evidence,'actual_usd':None,'reconciliation':'PENDING'}}
    output=encoded_result(data['script'],video)
    with engine.begin() as conn:
        job=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==old['owner_id']).with_for_update()).mappings().one()
        from .auth import active_user
        active_user(conn,job['owner_id'])
        if (job['configuration_snapshot'] or {}).get('video_recovery',{}).get('completed'):
            return {'job_id':job_id,'state':job['state'],'already_recovered':True,'mode':'apply'}
        if job['state']!='FAILED' or job['error_code']!='JOB_DEADLINE_EXCEEDED' or job['revision']!=old['revision']:
            raise EngineError('revision_conflict',409)
        rows=conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],m.tasks.c.job_id==job_id)
            .order_by(m.tasks.c.position).with_for_update()).mappings().all()
        if len(rows)!=2 or dict(rows[0])!=data['script_task'] or dict(rows[1])!=task:
            raise EngineError('revision_conflict',409)
        if conn.execute(select(m.results.c.id).where(m.results.c.owner_id==job['owner_id'],m.results.c.job_id==job_id)).first() or conn.execute(select(m.deliveries.c.id).where(m.deliveries.c.owner_id==job['owner_id'],m.deliveries.c.job_id==job_id)).first():
            raise EngineError('video_reconciliation_result_exists',409)
        agent=conn.execute(select(m.agents).where(m.agents.c.id==job['agent_id'],m.agents.c.owner_id==job['owner_id']).with_for_update()).mappings().one_or_none()
        if not agent or not job['legacy_task_id']:raise EngineError('VIDEO_TASK_NOT_AUTHORIZED',403)
        configured=ConfiguredTaskRepository(conn).rows(agent,job['legacy_task_id'])
        if not configured or configured[0]['tipo']!='VIDEO_GENERAR':raise EngineError('VIDEO_TASK_NOT_AUTHORIZED',403)
        provider=conn.execute(select(providers).where(providers.c.id==data['provider']['id']).with_for_update()).mappings().first()
        if not provider or provider['revision']!=data['provider']['revision'] or provider['credential_ciphertext']!=data['provider']['credential_ciphertext']:
            raise EngineError('video_reconciliation_provider_changed',409)
        from .shared_video_provider import resolve
        selected=resolve(conn,job['owner_id'])
        if selected['id']!=provider['id'] or selected['owner_id']!=provider['owner_id']:
            raise EngineError('video_reconciliation_provider_changed',409)
        validate_reservation(conn,job,rows[1],lock=True)
        transition(conn,job['owner_id'],reservation,'pending',now)
        revision=reopen_timed_out_video(conn,job,now)
        conn.execute(update(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==job['owner_id']).values(deadline_at=None))
        conn.execute(update(m.tasks).where(m.tasks.c.id==task['id'],m.tasks.c.owner_id==job['owner_id']).values(state='COMPLETED',output=output,lease_token=None,lease_until=None))
        current=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==job['owner_id'])).mappings().one()
        registry=default_registry(engine=engine)
        box=TaskBox(engine,registry=registry,clock=lambda:now)
        ExecutionManager(conn,registry).advance(box,conn,current,task,output)
        current=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==job['owner_id']).with_for_update()).mappings().one()
        if current['state']!='REVIEWING':raise EngineError('video_reconciliation_finalization_failed',409)
        snapshot={**current['configuration_snapshot'],'video_recovery':{'completed':True,'remote_id':task['provider_job_id']}}
        conn.execute(update(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==job['owner_id']).values(configuration_snapshot=snapshot))
        current=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==job['owner_id'])).mappings().one()
        result=eligible_result(conn,current)
        if result:
            dispatcher=Dispatcher(conn,now=now,registry=registry)
            dispatcher._transition(current,'DELIVERED',reason=REASON)
            conn.execute(insert(m.deliveries).values(id=str(uuid4()),owner_id=job['owner_id'],job_id=job_id,
                result_id=result['id'],state='DELIVERED',authorized_at=now,available_at=now,delivered_at=now))
        state='DELIVERED' if result else 'REVIEWING'
    return {'job_id':job_id,'state':state,'already_recovered':False,'mode':'apply'}
