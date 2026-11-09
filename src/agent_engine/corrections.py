"""Explicit, local-only correction retry. Preserves previous results/reviews."""
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, update, insert
from . import models as m
from .auth import now_utc
from .errors import EngineError
from .state_store import transition_job
from .tools import default_registry


def retry_local_correction(conn, *, owner_id, job_id, actor_id, expected_revision):
    now = now_utc()
    job = conn.execute(select(m.jobs).where(m.jobs.c.owner_id == owner_id,
        m.jobs.c.id == job_id).with_for_update()).mappings().first()
    if job is None:
        raise EngineError('job_not_found', 404)
    if job['revision'] != expected_revision:
        raise EngineError('revision_conflict', 409)
    if job['state'] != 'CORRECTION_REQUIRED':
        raise EngineError('job_not_correctable', 409)
    limit = job['request_snapshot'].get('limits', {}).get('max_corrections', 0)
    if job['correction_count'] > limit or job['correction_count'] > 2:
        raise EngineError('correction_budget_exhausted', 409)
    tasks = conn.execute(select(m.tasks).where(m.tasks.c.owner_id == owner_id,
        m.tasks.c.job_id == job_id).order_by(m.tasks.c.position).with_for_update()).mappings().all()
    # Never replay a billable/externally submitted action. The local demo is deterministic.
    if len(tasks) != 1 or tasks[0]['tool_id'] != 'dpia.test.echo' or any(
        task['provider_submission_state'] != 'NOT_SUBMITTED' for task in tasks):
        raise EngineError('correction_requires_manual_rebuild', 409)
    agent = conn.execute(select(m.agents).where(m.agents.c.owner_id == owner_id,
        m.agents.c.id == job['agent_id']).with_for_update()).mappings().first()
    grant = conn.execute(select(m.agent_capabilities.c.tool_id).where(
        m.agent_capabilities.c.owner_id == owner_id,
        m.agent_capabilities.c.agent_id == job['agent_id'],
        m.agent_capabilities.c.tool_id == 'dpia.test.echo')).first()
    if agent is None or agent['configuration_state'] != 'ENABLED' or grant is None:
        raise EngineError('agent_disabled_or_tool_revoked', 409)
    task = tasks[0]
    if task['attempt_count'] >= 3:
        raise EngineError('correction_attempts_exhausted', 409)
    duration = job['request_snapshot']['limits']['max_duration_seconds']
    # A review can happen after the original deadline. Explicit retry gets a fresh bounded deadline.
    revision = transition_job(conn, owner_id=owner_id, job_id=job_id,
        expected_revision=expected_revision, target='QUEUED', actor_id=actor_id,
        actor_type='SESSION', reason_code='CORRECTION_RETRY', now=now)
    conn.execute(update(m.jobs).where(m.jobs.c.owner_id == owner_id,
        m.jobs.c.id == job_id, m.jobs.c.revision == revision).values(
        progress=0, error_code=None, deadline_at=now+timedelta(seconds=duration)))
    conn.execute(update(m.tasks).where(m.tasks.c.owner_id == owner_id,
        m.tasks.c.id == task['id']).values(state='PENDING', output=None,
        lease_token=None, lease_until=None, lease_version=task['lease_version']+1,
        next_attempt_at=None))
    spec = default_registry().tools['dpia.test.echo']
    conn.execute(insert(m.outbox).values(id=str(uuid4()), owner_id=owner_id,
        job_id=job_id, task_id=task['id'], capability=spec.capability,
        event_key=f'job:{job_id}:correction:{job["correction_count"]}', available_at=now))
    return {'job_id': job_id, 'revision': revision, 'state': 'QUEUED'}
