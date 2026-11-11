"""MySQL task ownership, fencing and recovery using the installed 20 tables.

No DDL, provider calls or Redis connections. Construction performs no I/O.
"""
from dataclasses import dataclass
from datetime import timedelta
import json
from uuid import uuid4
from sqlalchemy import select, insert, update, func, and_
from model.usuario import Usuario
from . import models as m
from .auth import now_utc
from .dispatcher import Dispatcher
from .errors import EngineError
from .state_store import transition_job
from .tools import default_registry


@dataclass(frozen=True)
class QueuePolicy:
    lease_seconds: int = 30
    max_attempts: int = 3
    republish_seconds: int = 60

    def __post_init__(self):
        if not 5 <= self.lease_seconds <= 60 or not 1 <= self.max_attempts <= 10 or self.republish_seconds < 60:
            raise ValueError('invalid_queue_policy')


@dataclass(frozen=True)
class Lease:
    owner_id: int
    job_id: str
    task_id: str
    worker_id: str
    token: str
    version: int
    attempt_id: str
    tool_id: str
    parameters: dict
    previous_outputs: tuple


class TaskBox:
    def __init__(self, engine, *, registry=None, policy=None, clock=now_utc):
        self.engine = engine
        self.registry = registry or default_registry()
        self.policy = policy or QueuePolicy()
        self.clock = clock

    def now(self):
        # Installed columns are DATETIME(0); avoid fractional lease comparisons.
        return self.clock().replace(microsecond=0)

    def register_worker(self, worker_id, capabilities):
        if not worker_id or len(worker_id) > 120 or not capabilities or not set(capabilities).issubset(
                {tool.capability for tool in self.registry.tools.values()}):
            raise EngineError('invalid_worker')
        with self.engine.begin() as conn:
            if conn.execute(select(m.workers.c.id).where(m.workers.c.id == worker_id).with_for_update()).first():
                raise EngineError('worker_id_already_used', 409)
            conn.execute(insert(m.workers).values(id=worker_id, capabilities=sorted(set(capabilities)),
                reported_state='AVAILABLE', heartbeat_at=self.now(), current_task_id=None))

    def idle(self, worker_id, task_id=None):
        with self.engine.begin() as conn:
            predicate = m.workers.c.current_task_id.is_(None) if task_id is None else m.workers.c.current_task_id == task_id
            conn.execute(update(m.workers).where(m.workers.c.id == worker_id, predicate)
                .values(reported_state='AVAILABLE', heartbeat_at=self.now(), current_task_id=None))

    def authorized(self, conn, job, task, *, require_provider=True, check_integration=True):
        user = conn.execute(select(Usuario.id).where(Usuario.id == job['owner_id'],
            Usuario.activo.is_(True)).with_for_update()).first()
        if user is None:
            raise EngineError('owner_inactive', 403)
        principal = Dispatcher(conn, now=self.now())._scheduled_author({
            'owner_id': job['owner_id'], 'definition': {'author': {
                'kind': 'API_CLIENT' if job['client_id'] else 'SESSION',
                'actor_id': job['client_id'] or str(job['owner_id'])}}})
        from .management import locked_agent
        agent = locked_agent(conn, principal, job['agent_id'])
        from .pause_control import require_unpaused
        require_unpaused(conn,agent)
        if agent['configuration_state'] != 'ENABLED':
            raise EngineError('agent_paused', 409)
        capability = conn.execute(select(m.agent_capabilities.c.tool_id).where(
            m.agent_capabilities.c.owner_id == job['owner_id'], m.agent_capabilities.c.agent_id == job['agent_id'],
            m.agent_capabilities.c.tool_id == task['tool_id']).with_for_update()).first()
        if capability is None or task['tool_id'] not in job['configuration_snapshot'].get('capabilities', []):
            raise EngineError('tool_authorization_revoked', 403)
        spec = self.registry.tools.get(task['tool_id'])
        if spec is None:
            raise EngineError('unknown_tool', 403)
        if check_integration:
            from .integrations import require_enabled
            require_enabled(conn, spec.provider)
        if require_provider:
            from .integrations import BY_PROVIDER
            credential_filter = (m.connections.c.credential_ref == 'integration:' + BY_PROVIDER[spec.provider]
                                 if spec.provider in BY_PROVIDER else True)
            permitted = conn.execute(select(m.connections.c.id).join(m.tool_grants, and_(
                m.connections.c.owner_id == m.tool_grants.c.owner_id,
                m.connections.c.id == m.tool_grants.c.connection_id)).where(
                    m.tool_grants.c.owner_id == job['owner_id'], m.tool_grants.c.agent_id == job['agent_id'],
                    m.tool_grants.c.tool_id == task['tool_id'], m.connections.c.enabled.is_(True),
                    m.connections.c.provider_id == spec.provider, credential_filter).with_for_update()).first()
            if permitted is None:
                raise EngineError('provider_not_authorized', 403)
        return spec

    def _job(self, conn, owner, job_id):
        return conn.execute(select(m.jobs).where(m.jobs.c.owner_id == owner,
            m.jobs.c.id == job_id).with_for_update()).mappings().first()

    def _task(self, conn, owner, task_id):
        return conn.execute(select(m.tasks).where(m.tasks.c.owner_id == owner,
            m.tasks.c.id == task_id).with_for_update()).mappings().first()

    def _event(self, conn, job, event_type, **changes):
        revision = job['revision']+1
        count = conn.execute(update(m.jobs).where(m.jobs.c.owner_id == job['owner_id'],
            m.jobs.c.id == job['id'], m.jobs.c.revision == job['revision']).values(
                revision=revision, updated_at=self.now(), **changes)).rowcount
        if count != 1:
            raise EngineError('revision_conflict', 409)
        conn.execute(insert(m.events).values(id=str(uuid4()), owner_id=job['owner_id'], job_id=job['id'],
            sequence=revision, type=event_type, actor_type='SYSTEM', actor_id='task-box',
            correlation_id=job['correlation_id'], created_at=self.now()))

    def _fail(self, conn, job, code):
        if job['state'] in ('QUEUED', 'RUNNING'):
            revision = transition_job(conn, owner_id=job['owner_id'], job_id=job['id'],
                expected_revision=job['revision'], target='FAILED', actor_id='task-box',
                reason_code=code, now=self.now())
            conn.execute(update(m.jobs).where(m.jobs.c.owner_id == job['owner_id'],
                m.jobs.c.id == job['id'], m.jobs.c.revision == revision).values(error_code=code))
        ids = select(m.tasks.c.id).where(m.tasks.c.owner_id == job['owner_id'], m.tasks.c.job_id == job['id'])
        conn.execute(update(m.workers).where(m.workers.c.current_task_id.in_(ids))
            .values(current_task_id=None, reported_state='AVAILABLE', heartbeat_at=self.now()))
        conn.execute(update(m.attempts).where(m.attempts.c.owner_id == job['owner_id'],
            m.attempts.c.task_id.in_(ids), m.attempts.c.state == 'RUNNING')
            .values(state='FAILED', error_code=code, finished_at=self.now()))
        conn.execute(update(m.tasks).where(m.tasks.c.owner_id == job['owner_id'], m.tasks.c.job_id == job['id'],
            m.tasks.c.state.not_in(['COMPLETED', 'FAILED', 'CANCELLED'])).values(
                state='FAILED', lease_token=None, lease_until=None, lease_version=m.tasks.c.lease_version+1))

    def _rearm(self, conn, job, task, available):
        key = f"job:{job['id']}:step:{task['position']}"
        row = conn.execute(select(m.outbox.c.id).where(m.outbox.c.owner_id == job['owner_id'],
            m.outbox.c.event_key == key).with_for_update()).first()
        values = dict(available_at=available, published_at=None, stream_message_id=None)
        if row:
            conn.execute(update(m.outbox).where(m.outbox.c.id == row.id,
                m.outbox.c.owner_id == job['owner_id']).values(**values))
        else:
            conn.execute(insert(m.outbox).values(id=str(uuid4()), owner_id=job['owner_id'], job_id=job['id'],
                task_id=task['id'], event_key=key, capability=self.registry.tools[task['tool_id']].capability, **values))

    def claim(self, worker_id, capability, message, *, require_provider=True):
        """Return (LEASE|DEFER|ACK, lease). Redis supplies references, never input."""
        with self.engine.begin() as conn:
            job = self._job(conn, message.owner_id, message.job_id)
            if job is None or job['state'] not in ('QUEUED', 'RUNNING'):
                return 'ACK', None
            task = self._task(conn, job['owner_id'], message.task_id)
            source = conn.execute(select(m.outbox).where(m.outbox.c.owner_id == job['owner_id'],
                m.outbox.c.id == message.outbox_id, m.outbox.c.job_id == job['id'],
                m.outbox.c.task_id == message.task_id).with_for_update()).mappings().first()
            if task is None or task['job_id'] != job['id'] or source is None or source['capability'] != capability:
                return 'ACK', None
            if task['state'] in ('COMPLETED', 'FAILED', 'CANCELLED'):
                return 'ACK', None
            if (task['state'] != 'PENDING' or (task['next_attempt_at'] and task['next_attempt_at'] > self.now())
                    or task['provider_submission_state'] != 'NOT_SUBMITTED'):
                return 'DEFER', None
            if job['deadline_at'] and job['deadline_at'] <= self.now():
                self._fail(conn, job, 'JOB_DEADLINE_EXCEEDED')
                return 'ACK', None
            try:
                spec = self.authorized(conn, job, task, require_provider=require_provider)
            except EngineError as error:
                if error.code in ('agent_paused', 'integration_disabled'):
                    return 'DEFER', None
                self._fail(conn, job, error.code)
                return 'ACK', None
            if spec.capability != capability:
                return 'ACK', None
            previous = conn.execute(select(m.tasks).where(m.tasks.c.owner_id == job['owner_id'],
                m.tasks.c.job_id == job['id'], m.tasks.c.position < task['position'])
                .order_by(m.tasks.c.position).with_for_update()).mappings().all()
            if any(row['state'] != 'COMPLETED' for row in previous):
                return 'DEFER', None
            worker = conn.execute(select(m.workers).where(m.workers.c.id == worker_id).with_for_update()).mappings().first()
            if worker is None or capability not in worker['capabilities'] or worker['current_task_id'] is not None:
                return 'DEFER', None
            used = conn.execute(select(func.sum(m.tasks.c.attempt_count)).where(
                m.tasks.c.owner_id == job['owner_id'], m.tasks.c.job_id == job['id'])).scalar() or 0
            budget = job['request_snapshot'].get('limits', {}).get('max_tool_calls', 0)
            if task['tool_id'] == 'dpia.test.echo':
                budget *= (1 + min(job['correction_count'],
                    job['request_snapshot'].get('limits', {}).get('max_corrections', 0)))
            if task['attempt_count'] >= self.policy.max_attempts or used >= budget:
                self._fail(conn, job, 'TASK_ATTEMPT_BUDGET_EXCEEDED')
                return 'ACK', None
            token, attempt_id = str(uuid4()), str(uuid4())
            version, number = task['lease_version']+1, task['attempt_count']+1
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id == job['owner_id'], m.tasks.c.id == task['id'])
                .values(state='RUNNING', lease_token=token, lease_version=version, attempt_count=number,
                        lease_until=self.now()+timedelta(seconds=self.policy.lease_seconds), next_attempt_at=None))
            conn.execute(insert(m.attempts).values(id=attempt_id, owner_id=job['owner_id'], task_id=task['id'],
                number=number, worker_id=worker_id, lease_token=token, provider_id=spec.provider,
                state='RUNNING', started_at=self.now()))
            conn.execute(update(m.workers).where(m.workers.c.id == worker_id).values(
                reported_state='BUSY', heartbeat_at=self.now(), current_task_id=task['id']))
            if job['state'] == 'QUEUED':
                transition_job(conn, owner_id=job['owner_id'], job_id=job['id'], expected_revision=job['revision'],
                    target='RUNNING', actor_id=worker_id, now=self.now())
            return 'LEASE', Lease(job['owner_id'], job['id'], task['id'], worker_id, token, version,
                attempt_id, task['tool_id'], task['input_snapshot'].get('parameters', {}),
                tuple(row['output'] for row in previous))

    def _owned(self, conn, lease):
        job = self._job(conn, lease.owner_id, lease.job_id)
        task = self._task(conn, lease.owner_id, lease.task_id)
        attempt = conn.execute(select(m.attempts).where(m.attempts.c.owner_id == lease.owner_id,
            m.attempts.c.id == lease.attempt_id, m.attempts.c.worker_id == lease.worker_id,
            m.attempts.c.lease_token == lease.token, m.attempts.c.state == 'RUNNING').with_for_update()).first()
        if (job is None or job['state'] != 'RUNNING' or task is None or attempt is None or
                task['state'] != 'RUNNING' or task['lease_token'] != lease.token or
                task['lease_version'] != lease.version or task['lease_until'] is None or task['lease_until'] <= self.now()):
            raise EngineError('lease_lost', 409)
        if job['deadline_at'] and job['deadline_at'] <= self.now():
            raise EngineError('lease_lost', 409)
        return job, task

    def heartbeat(self, lease):
        with self.engine.begin() as conn:
            self._owned(conn, lease)
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id == lease.owner_id, m.tasks.c.id == lease.task_id)
                .values(lease_until=self.now()+timedelta(seconds=self.policy.lease_seconds)))
            conn.execute(update(m.workers).where(m.workers.c.id == lease.worker_id,
                m.workers.c.current_task_id == lease.task_id).values(heartbeat_at=self.now(), reported_state='BUSY'))

    def mark_submitting(self, lease, expected_integration_revision=None):
        """Persist BEFORE any externally billable action. Recovery then fails closed."""
        with self.engine.begin() as conn:
            job, task = self._owned(conn, lease)
            spec = self.authorized(conn, job, task, require_provider=lease.tool_id != 'dpia.test.echo')
            if expected_integration_revision is not None:
                from .integrations import BY_PROVIDER
                from .integration_models import integrations
                current = conn.execute(select(integrations.c.revision).where(
                    integrations.c.id == BY_PROVIDER.get(spec.provider)).with_for_update()).scalar()
                if current != expected_integration_revision:
                    raise EngineError('revision_conflict', 409)
            if task['provider_submission_state'] != 'NOT_SUBMITTED':
                raise EngineError('provider_already_submitted', 409)
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id == lease.owner_id,
                m.tasks.c.id == lease.task_id).values(provider_submission_state='SUBMITTING'))

    def mark_submitted(self, lease, provider_job_id):
        if not isinstance(provider_job_id, str) or not 1 <= len(provider_job_id) <= 160:
            raise EngineError('invalid_provider_reference')
        with self.engine.begin() as conn:
            job, task = self._owned(conn, lease)
            if task['provider_submission_state'] != 'SUBMITTING':
                raise EngineError('provider_submission_not_recorded', 409)
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id == lease.owner_id, m.tasks.c.id == lease.task_id)
                .values(provider_submission_state='SUBMITTED', provider_job_id=provider_job_id))
            conn.execute(update(m.attempts).where(m.attempts.c.owner_id == lease.owner_id,
                m.attempts.c.id == lease.attempt_id).values(provider_request_id=provider_job_id))

    def complete(self, lease, output, *, require_provider=True):
        try:
            serialized = json.dumps(output, allow_nan=False)
            if not isinstance(output, dict) or len(serialized.encode()) > 262144:
                raise ValueError
        except (ValueError, TypeError):
            raise EngineError('invalid_task_output') from None
        with self.engine.begin() as conn:
            job, task = self._owned(conn, lease)
            try:
                self.authorized(conn, job, task, require_provider=require_provider,
                    check_integration=task['provider_submission_state'] == 'NOT_SUBMITTED')
            except EngineError as error:
                self._fail(conn, job, error.code)
                return
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id == lease.owner_id, m.tasks.c.id == lease.task_id)
                .values(state='COMPLETED', output=output, lease_token=None, lease_until=None))
            conn.execute(update(m.attempts).where(m.attempts.c.id == lease.attempt_id,
                m.attempts.c.owner_id == lease.owner_id).values(state='COMPLETED', finished_at=self.now()))
            next_task = conn.execute(select(m.tasks).where(m.tasks.c.owner_id == lease.owner_id,
                m.tasks.c.job_id == lease.job_id, m.tasks.c.position == task['position']+1)
                .with_for_update()).mappings().first()
            total = conn.execute(select(func.count()).select_from(m.tasks).where(
                m.tasks.c.owner_id == lease.owner_id, m.tasks.c.job_id == lease.job_id)).scalar_one()
            if next_task:
                conn.execute(update(m.tasks).where(m.tasks.c.owner_id == lease.owner_id,
                    m.tasks.c.id == next_task['id']).values(state='PENDING'))
                self._rearm(conn, job, next_task, self.now())
                self._event(conn, job, 'TASK_COMPLETED', progress=int(100*(task['position']+1)/total))
            else:
                version = (conn.execute(select(func.max(m.results.c.version)).where(
                    m.results.c.owner_id == lease.owner_id, m.results.c.job_id == lease.job_id)).scalar() or 0)+1
                conn.execute(insert(m.results).values(id=str(uuid4()), owner_id=lease.owner_id,
                    job_id=lease.job_id, version=version, schema_version='agents.task-output.v1', payload=output,
                    evidence_status='UNVERIFIED', created_at=self.now(), approved_at=None))
                revision = transition_job(conn, owner_id=lease.owner_id, job_id=lease.job_id,
                    expected_revision=job['revision'], target='REVIEWING', actor_id=lease.worker_id, now=self.now())
                conn.execute(update(m.jobs).where(m.jobs.c.owner_id == lease.owner_id,
                    m.jobs.c.id == lease.job_id, m.jobs.c.revision == revision).values(progress=100))
            conn.execute(update(m.workers).where(m.workers.c.id == lease.worker_id,
                m.workers.c.current_task_id == lease.task_id).values(
                    current_task_id=None, reported_state='AVAILABLE', heartbeat_at=self.now()))

    def _retry_or_block(self, conn, job, task, *, recovery=False):
        uncertain = task['provider_submission_state'] != 'NOT_SUBMITTED'
        if not uncertain and task['attempt_count'] >= self.policy.max_attempts:
            self._fail(conn, job, 'TASK_ATTEMPTS_EXHAUSTED')
            return
        delay = min(60, 2**min(task['attempt_count'], 6))
        due = self.now()+timedelta(seconds=delay)
        conn.execute(update(m.tasks).where(m.tasks.c.owner_id == task['owner_id'], m.tasks.c.id == task['id'])
            .values(state='BLOCKED_UNCERTAIN' if uncertain else 'PENDING', lease_token=None, lease_until=None,
                    lease_version=task['lease_version']+1, next_attempt_at=None if uncertain else due,
                    provider_submission_state='SUBMISSION_UNCERTAIN' if uncertain else 'NOT_SUBMITTED'))
        conn.execute(update(m.attempts).where(m.attempts.c.owner_id == task['owner_id'],
            m.attempts.c.task_id == task['id'], m.attempts.c.state == 'RUNNING').values(
                state='UNCERTAIN' if uncertain else 'RETRYABLE_ERROR',
                error_code='PROVIDER_CONFIRMATION_REQUIRED' if uncertain else 'LEASE_EXPIRED' if recovery else 'HANDLER_FAILED',
                finished_at=self.now()))
        conn.execute(update(m.workers).where(m.workers.c.current_task_id == task['id']).values(
            current_task_id=None, reported_state='AVAILABLE'))
        if not uncertain:
            self._rearm(conn, job, task, due)
        self._event(conn, job, 'TASK_UNCERTAIN' if uncertain else 'TASK_RECOVERED' if recovery else 'TASK_RETRY_SCHEDULED')

    def defer_integration(self, lease):
        with self.engine.begin() as conn:
            job, task = self._owned(conn, lease)
            if task['provider_submission_state'] != 'NOT_SUBMITTED':
                raise EngineError('provider_already_submitted', 409)
            conn.execute(update(m.tasks).where(m.tasks.c.id == lease.task_id,
                m.tasks.c.owner_id == lease.owner_id).values(state='PENDING', lease_token=None,
                    lease_until=None, lease_version=m.tasks.c.lease_version + 1))
            conn.execute(update(m.attempts).where(m.attempts.c.id == lease.attempt_id,
                m.attempts.c.owner_id == lease.owner_id).values(state='DEFERRED', finished_at=self.now()))
            conn.execute(update(m.workers).where(m.workers.c.id == lease.worker_id,
                m.workers.c.current_task_id == lease.task_id).values(current_task_id=None, reported_state='AVAILABLE'))
            self._event(conn, job, 'TASK_INTEGRATION_DEFERRED')

    def failed(self, lease):
        with self.engine.begin() as conn:
            job, task = self._owned(conn, lease)
            self._retry_or_block(conn, job, task)

    def recover(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise EngineError('invalid_batch_size')
        count = 0
        with self.engine.begin() as conn:
            expired_task = select(m.tasks.c.id).where(m.tasks.c.owner_id == m.jobs.c.owner_id,
                m.tasks.c.job_id == m.jobs.c.id, m.tasks.c.state == 'RUNNING',
                m.tasks.c.lease_until <= self.now()).exists()
            lost_distribution = select(m.outbox.c.id).join(m.tasks, and_(
                m.tasks.c.owner_id == m.outbox.c.owner_id, m.tasks.c.id == m.outbox.c.task_id)).where(
                    m.outbox.c.owner_id == m.jobs.c.owner_id, m.outbox.c.job_id == m.jobs.c.id,
                    m.outbox.c.published_at <= self.now()-timedelta(seconds=self.policy.republish_seconds),
                    m.tasks.c.state == 'PENDING', m.tasks.c.provider_submission_state == 'NOT_SUBMITTED').exists()
            rows = conn.execute(select(m.jobs).where(m.jobs.c.state.in_(['QUEUED', 'RUNNING']))
                .where((m.jobs.c.deadline_at <= self.now()) | expired_task | lost_distribution)
                .order_by(m.jobs.c.updated_at, m.jobs.c.id).limit(limit)
                .with_for_update(skip_locked=True)).mappings().all()
            for job in rows:
                if job['deadline_at'] and job['deadline_at'] <= self.now():
                    self._fail(conn, job, 'JOB_DEADLINE_EXCEEDED')
                    count += 1
                    continue
                expired = conn.execute(select(m.tasks).where(m.tasks.c.owner_id == job['owner_id'],
                    m.tasks.c.job_id == job['id'], m.tasks.c.state == 'RUNNING',
                    m.tasks.c.lease_until <= self.now()).with_for_update()).mappings().all()
                for task in expired:
                    current = self._job(conn, job['owner_id'], job['id'])
                    self._retry_or_block(conn, current, task, recovery=True)
                    count += 1
                # Redis loss, deleted PEL entries or a crash between stores cannot
                # strand ready MySQL work. Duplicates remain fenced by claim().
                ready = conn.execute(select(m.tasks).where(m.tasks.c.owner_id == job['owner_id'],
                    m.tasks.c.job_id == job['id'], m.tasks.c.state == 'PENDING',
                    m.tasks.c.provider_submission_state == 'NOT_SUBMITTED').with_for_update()).mappings().all()
                for task in ready:
                    old = conn.execute(select(m.outbox).where(m.outbox.c.owner_id == job['owner_id'],
                        m.outbox.c.task_id == task['id']).with_for_update()).mappings().first()
                    if old and old['published_at'] and old['published_at'] <= self.now()-timedelta(seconds=self.policy.republish_seconds):
                        self._rearm(conn, job, task, max(self.now(), task['next_attempt_at'] or self.now()))
                        count += 1
        return count
