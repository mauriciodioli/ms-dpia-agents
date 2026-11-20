"""Read-only inspection of a timed-out video; never submits or changes a job."""
import json
import re
from urllib.parse import urlsplit
from sqlalchemy import select
from . import models as m
from .errors import EngineError
from .rest_providers.models import providers
from .rest_providers.service import Service
from .video_worker import prior_script


def inspect_video(engine, config, job_id, *, service=None, _internal=False):
    from uuid import UUID
    try:
        if str(UUID(job_id)) != job_id: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise EngineError('invalid_job_id', 422) from None
    with engine.connect() as conn:
        job=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id)).mappings().first()
        if not job: raise EngineError('job_not_found',404)
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
        if conn.execute(select(m.results.c.id).where(m.results.c.owner_id==job['owner_id'],m.results.c.job_id==job_id)).first() or conn.execute(select(m.deliveries.c.id).where(m.deliveries.c.owner_id==job['owner_id'],m.deliveries.c.job_id==job_id)).first():
            raise EngineError('video_reconciliation_result_exists',409)
        provider=conn.execute(select(providers).where(providers.c.id==checkpoint.get('provider_id'),
            providers.c.adapter=='heygen')).mappings().first()
        if (not provider or provider['revision']!=checkpoint.get('provider_revision')
                or not provider['credential_ciphertext'] or provider['credential_origin']!=provider['base_url']):
            raise EngineError('video_reconciliation_provider_changed',409)
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
            'script':script_value,'checkpoint':checkpoint,'provider':provider,'url':url}
    return (report,None) if _internal else report
