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
        require_transition(row['state'], target)
        now = now or now_utc()
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
