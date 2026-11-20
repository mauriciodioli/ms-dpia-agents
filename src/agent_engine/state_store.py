"""Internal atomic state primitive, not a Dispatcher or public mutation API.

The caller supplies a previously authorized owner and owns the outer transaction.
No provider, scheduling or delivery side effect is performed here.
"""
from uuid import uuid4
from sqlalchemy import select, update, insert
from .auth import now_utc
from .errors import EngineError
from .models import jobs, events
from .states import require_transition


def reopen_timed_out_video(conn, job, now):
    """One audited reconciliation transition; caller must hold and validate the job."""
    if job['state']!='FAILED' or job['error_code']!='JOB_DEADLINE_EXCEEDED':
        raise EngineError('video_reconciliation_not_eligible',409)
    revision=job['revision']+1
    changed=conn.execute(update(jobs).where(jobs.c.id==job['id'],jobs.c.owner_id==job['owner_id'],
        jobs.c.state=='FAILED',jobs.c.revision==job['revision'],jobs.c.error_code=='JOB_DEADLINE_EXCEEDED')
        .values(state='RUNNING',revision=revision,error_code=None,finished_at=None,updated_at=now)).rowcount
    if changed!=1:raise EngineError('revision_conflict',409)
    conn.execute(insert(events).values(id=str(uuid4()),owner_id=job['owner_id'],job_id=job['id'],
        sequence=revision,type='VIDEO_RECOVERY_STARTED',actor_type='ADMIN',actor_id='agent-video-recover',
        reason_code='PROVIDER_COMPLETED',correlation_id=job['correlation_id'],created_at=now))
    return revision


def transition_job(conn, *, owner_id: int, job_id: str, expected_revision: int,
                   target: str, actor_id: str, reason_code: str | None = None,
                   actor_type: str = 'SYSTEM', now=None) -> int:
    if type(expected_revision) is not int or expected_revision < 1:
        raise EngineError('invalid_revision')
    with conn.begin_nested():
        row = conn.execute(select(jobs).where(jobs.c.owner_id == owner_id,
            jobs.c.id == job_id).with_for_update()).mappings().first()
        if row is None:
            raise EngineError('job_not_found', 404)
        if row['revision'] != expected_revision:
            raise EngineError('revision_conflict', 409)
        now = now or now_utc()
        informational = row['state'] == 'REVIEWING' and target == 'DELIVERED'
        if informational:
            from .informational_delivery import REASON, eligible_result, accepted_video
            if (actor_type != 'SYSTEM' or actor_id != 'dispatcher' or reason_code != REASON or
                    (not accepted_video(row) and row['deliver_not_before'] is not None and row['deliver_not_before'] > now) or
                    eligible_result(conn, row) is None):
                raise EngineError('invalid_transition', 409)
        require_transition(row['state'], target, informational=informational)
        changes = dict(state=target, revision=expected_revision+1, updated_at=now)
        if target == 'RUNNING' and row['started_at'] is None:
            changes['started_at'] = now
        if target in ('DELIVERED', 'FAILED', 'CANCELLED'):
            changes['finished_at'] = now
        count = conn.execute(update(jobs).where(jobs.c.owner_id == owner_id, jobs.c.id == job_id,
            jobs.c.revision == expected_revision, jobs.c.state == row['state']).values(**changes)).rowcount
        if count != 1:
            raise EngineError('revision_conflict', 409)
        conn.execute(insert(events).values(id=str(uuid4()), owner_id=owner_id, job_id=job_id,
            sequence=expected_revision+1, type=target, actor_type=actor_type, actor_id=actor_id,
            reason_code=reason_code, correlation_id=row['correlation_id'], created_at=now))
    return expected_revision+1
