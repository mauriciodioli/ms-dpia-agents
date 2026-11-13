"""Transactional Dispatcher. Produces MySQL outbox records, never provider calls."""
from datetime import timedelta
from hashlib import sha256
import json
import re
from uuid import uuid4, uuid5, NAMESPACE_URL
from sqlalchemy import or_, select, insert, update, and_
from model.usuario import Usuario
from . import models as m
from .auth import Principal, SCOPES, now_utc
from .contracts import REQUEST_CREATE, SCHEDULE_REQUEST, REVISION, validate, utc, iso
from .errors import EngineError
from .management import locked_agent, audit_agent
from .repository import ReadRepository
from .scheduling import next_occurrence, delivery_time
from .state_store import transition_job
from .tools import default_registry


def request_hash(body):
    try:
        return sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                 allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError):
        raise EngineError('invalid_contract') from None


def idempotency_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}', value):
        raise EngineError('idempotency_key_required')
    return value


class Dispatcher:
    def __init__(self, conn, *, now=None, registry=None):
        self.conn = conn
        self.now = now or now_utc()
        self.registry = registry or default_registry(conn=conn)

    def _prepare(self, agent, body):
        from .pause_control import require_unpaused
        require_unpaused(self.conn, agent)
        validate(REQUEST_CREATE, body)
        allowed = set(self.conn.execute(select(m.agent_capabilities.c.tool_id).where(
            m.agent_capabilities.c.owner_id == agent['owner_id'],
            m.agent_capabilities.c.agent_id == agent['id'])).scalars())
        # Centrally enabled LOW MCP tools do not require per-agent capability rows.
        from .mcp_repository import MCPRepository, tool_id
        allowed.update(tool_id(row['id']) for row in MCPRepository(self.conn).catalog(agent['owner_id'])
                       if row['risk_level']=='LOW' and row['tool_name'] in ('web_search_exa','web_fetch_exa'))
        for name, value in body['limits'].items():
            if value > agent['limits'].get(name, 0):
                raise EngineError('agent_budget_exceeded', 403)
        if len(body['pipeline']) > body['limits']['max_tool_calls']:
            raise EngineError('tool_call_budget_exceeded')
        pipeline = []
        for step in body['pipeline']:
            effective = {'tool': step['tool'], 'parameters': {
                **agent['search_parameters'].get(step['tool'], {}), **step['parameters']}}
            if step['tool'].startswith('mcp.'):
                from .mcp_catalog import require_tool
                require_tool(self.conn,agent['owner_id'],agent['id'],step['tool'])
            self.registry.validate_step(effective, allowed)
            pipeline.append(effective)
        return {**body, 'pipeline': pipeline}, allowed

    def _transition(self, row, target, principal=None, reason=None):
        return transition_job(self.conn, owner_id=row['owner_id'], job_id=row['id'],
            expected_revision=row['revision'], target=target,
            actor_id=principal.actor_id if principal else 'dispatcher',
            actor_type=principal.kind if principal else 'SYSTEM', reason_code=reason, now=self.now)

    def _queue(self, row):
        task = self.conn.execute(select(m.tasks).where(m.tasks.c.owner_id == row['owner_id'],
            m.tasks.c.job_id == row['id'], m.tasks.c.position == 0)).mappings().first()
        if task is None or task['tool_id'] not in self.registry.tools:
            raise EngineError('job_tool_unavailable', 409)
        capability = self.registry.tools[task['tool_id']].capability
        self._transition(row, 'QUEUED')
        self.conn.execute(insert(m.outbox).values(id=str(uuid4()), owner_id=row['owner_id'],
            job_id=row['id'], task_id=task['id'], capability=capability,
            event_key='job:'+row['id']+':step:0', available_at=self.now))

    def _fail(self, row, reason='DISPATCH_DEADLINE_EXCEEDED'):
        revision = self._transition(row, 'FAILED', reason=reason)
        self.conn.execute(update(m.jobs).where(m.jobs.c.owner_id == row['owner_id'],
            m.jobs.c.id == row['id'], m.jobs.c.revision == revision).values(error_code=reason))
        self.conn.execute(update(m.tasks).where(m.tasks.c.owner_id == row['owner_id'],
            m.tasks.c.job_id == row['id'], m.tasks.c.state.in_(['PENDING', 'WAITING_DEPENDENCY'])).values(state='FAILED'))

    def submit(self, principal, agent_id, body, key, *, schedule_id=None, slot=None):
        principal.require('jobs:create')
        validate(REQUEST_CREATE, body)
        key = idempotency_key(key)
        fingerprint = request_hash(body)
        agent = locked_agent(self.conn, principal, agent_id)
        previous = self.conn.execute(select(m.jobs).where(m.jobs.c.owner_id == principal.owner_id,
            m.jobs.c.agent_id == agent_id, m.jobs.c.idempotency_key == key).with_for_update()).mappings().first()
        if previous:
            if previous['request_hash'] != fingerprint:
                raise EngineError('idempotency_conflict', 409)
            return previous, False
        if agent['configuration_state'] != 'ENABLED':
            raise EngineError('agent_disabled', 409)
        legacy_task_id=None
        if schedule_id is not None:
            schedule=self.conn.execute(select(m.schedules).where(m.schedules.c.id==schedule_id,
                m.schedules.c.owner_id==principal.owner_id,m.schedules.c.agent_id==agent_id).with_for_update()).mappings().first()
            if schedule is None:raise EngineError('schedule_not_found',404)
            legacy_task_id=schedule['legacy_task_id']
            if legacy_task_id is not None:
                from .configured_task_repository import ConfiguredTaskRepository
                tasks=ConfiguredTaskRepository(self.conn).rows(agent,legacy_task_id)
                if not tasks or not tasks[0]['habilitada'] or (tasks[0]['parametros'] or {}).get('_deleted_at'):
                    raise EngineError('task_paused',409)
        from .execution_manager import ExecutionManager
        # Generate job_id early for planner token tracking
        job_id = str(uuid4())
        manager = ExecutionManager(self.conn, self.registry)
        effective_body = manager.prepare(agent, body, job_id=job_id)
        if any(step['tool'].startswith('mcp.') for step in effective_body['pipeline']):principal.require('mcp:execute')
        prepared, allowed = self._prepare(agent, effective_body)
        execution = utc(body['execute_at']) if 'execute_at' in body else self.now
        if schedule_id is None and 'execute_at' in body and execution < self.now:
            raise EngineError('execution_time_in_past')
        deadline = utc(body['deadline_at']) if 'deadline_at' in body else execution+timedelta(seconds=body['limits']['max_duration_seconds'])
        if deadline <= execution:
            raise EngineError('invalid_deadline')
        mcp_versions={}
        for step in prepared['pipeline']:
            if step['tool'].startswith('mcp.'):
                from .mcp_catalog import require_tool
                mcp_versions[step['tool']]=require_tool(self.conn,agent['owner_id'],agent['id'],step['tool'])[2]
        values = dict(id=job_id, owner_id=principal.owner_id, agent_id=agent_id,
            client_id=principal.actor_id if principal.kind == 'API_CLIENT' else None,
            schedule_id=schedule_id, schedule_slot=slot, legacy_task_id=legacy_task_id, idempotency_key=key, request_hash=fingerprint,
            correlation_id=str(uuid4()), state='CREATED', revision=1, agent_revision=agent['revision'],
            request_snapshot=prepared, configuration_snapshot={
                'name': agent['name'], 'instructions': agent['instructions'], 'limits': agent['limits'],
                'capabilities': sorted(allowed), 'revision': agent['revision'], 'mcp_tools':mcp_versions},
            priority=body.get('priority', 0), progress=None, execute_at=execution,
            deliver_not_before=utc(body['deliver_not_before']) if 'deliver_not_before' in body else execution,
            deadline_at=deadline, created_at=self.now, updated_at=self.now)
        self.conn.execute(insert(m.jobs).values(**values))
        if manager.planner_usage:
            self.conn.execute(insert(m.usage).values(id=str(uuid4()),
                owner_id=principal.owner_id, job_id=job_id,
                created_at=self.now, **manager.planner_usage))
        self.conn.execute(insert(m.events).values(id=str(uuid4()), owner_id=principal.owner_id,
            job_id=job_id, sequence=1, type='CREATED', actor_type=principal.kind,
            actor_id=principal.actor_id, correlation_id=values['correlation_id'], created_at=self.now))
        for position, step in enumerate(prepared['pipeline']):
            self.conn.execute(insert(m.tasks).values(id=str(uuid4()), owner_id=principal.owner_id,
                job_id=job_id, position=position, tool_id=step['tool'],
                state='PENDING' if position == 0 else 'WAITING_DEPENDENCY', input_snapshot=step))
        if deadline <= self.now:
            self._fail(values)
        elif execution <= self.now and schedule_id is None:
            self._queue(values)
        else:
            self._transition(values, 'SCHEDULED', principal)
        row = self.conn.execute(select(m.jobs).where(m.jobs.c.id == job_id,
            m.jobs.c.owner_id == principal.owner_id)).mappings().one()
        return row, True

    def create_schedule(self, principal, agent_id, body, key):
        principal.require('jobs:create')
        validate(SCHEDULE_REQUEST, body)
        key = idempotency_key(key)
        fingerprint = request_hash(body)
        schedule_id = str(uuid5(NAMESPACE_URL, f'ms-dpia-agents:{principal.owner_id}:{agent_id}:{key}'))
        agent = locked_agent(self.conn, principal, agent_id)
        previous = self.conn.execute(select(m.schedules).where(m.schedules.c.owner_id == principal.owner_id,
            m.schedules.c.id == schedule_id).with_for_update()).mappings().first()
        if previous:
            if previous['definition']['request_hash'] != fingerprint:
                raise EngineError('idempotency_conflict', 409)
            return previous, False
        template = body['request']
        if any(name in template for name in ('execute_at', 'deadline_at', 'deliver_not_before')):
            raise EngineError('recurrence_requires_relative_times')
        # Scheduled objective-only requests are planned when their execution becomes due.
        if 'pipeline' in template:
            if any(step['tool'].startswith('mcp.') for step in template['pipeline']):principal.require('mcp:execute')
            self._prepare(agent, template)
        definition = {key: value for key, value in body.items() if key != 'request'}
        due = next_occurrence(definition, self.now)
        if due is None:raise EngineError('execution_time_in_past',422)
        delivery_time(definition, due)  # Reject an invalid first delivery date too.
        definition.update(request=template, request_hash=fingerprint,
                          author={'kind': principal.kind, 'actor_id': principal.actor_id})
        row = dict(id=schedule_id, owner_id=principal.owner_id, agent_id=agent_id,
            timezone=body['timezone'], definition=definition, enabled=True, revision=1,
            next_run_at=due, created_at=self.now)
        self.conn.execute(insert(m.schedules).values(**row))
        audit_agent(self.conn, principal, agent, 'SCHEDULE_CREATED', {'schedule_id': schedule_id}, self.now)
        return row, True

    def deactivate_schedule(self, principal, schedule_id, body):
        principal.require('jobs:create')
        validate(REVISION, body)
        row = self.conn.execute(select(m.schedules).where(m.schedules.c.owner_id == principal.owner_id,
            m.schedules.c.id == schedule_id).with_for_update()).mappings().first()
        if row is None:
            raise EngineError('schedule_not_found', 404)
        agent = locked_agent(self.conn, principal, row['agent_id'])
        if row['revision'] != body['expected_revision']:
            raise EngineError('revision_conflict', 409)
        self.conn.execute(update(m.schedules).where(m.schedules.c.id == schedule_id,
            m.schedules.c.owner_id == principal.owner_id, m.schedules.c.revision == row['revision'])
            .values(enabled=False, next_run_at=None, revision=row['revision']+1))
        audit_agent(self.conn, principal, agent, 'SCHEDULE_DISABLED', {'schedule_id': schedule_id}, self.now)
        return {'id': schedule_id, 'enabled': False, 'revision': row['revision']+1}

    def cancel(self, principal, job_id, body):
        principal.require('jobs:create')
        validate(REVISION, body)
        row = ReadRepository(self.conn, principal).job(job_id)
        if row['state'] not in ('CREATED', 'SCHEDULED', 'QUEUED'):
            raise EngineError('job_not_cancellable', 409)
        if row['revision'] != body['expected_revision']:
            raise EngineError('revision_conflict', 409)
        self._transition(row, 'CANCELLED', principal)
        self.conn.execute(update(m.tasks).where(m.tasks.c.owner_id == principal.owner_id,
            m.tasks.c.job_id == job_id, m.tasks.c.state.in_(['PENDING', 'WAITING_DEPENDENCY'])).values(state='CANCELLED'))
        return ReadRepository(self.conn, principal).job(job_id)

    def _scheduled_author(self, schedule):
        owner = schedule['owner_id']
        author = schedule['definition']['author']
        if author['kind'] == 'API_CLIENT':
            client = self.conn.execute(select(m.clients).where(m.clients.c.owner_id == owner,
                m.clients.c.id == author['actor_id']).with_for_update()).mappings().first()
            if (client is None or client['revoked_at'] is not None or client['expires_at'] <= self.now
                    or 'jobs:create' not in client['scopes']):
                raise EngineError('schedule_authorization_revoked', 403)
            grants = frozenset(self.conn.execute(select(m.client_grants.c.agent_id).where(
                m.client_grants.c.owner_id == owner, m.client_grants.c.client_id == client['id'])).scalars())
            return Principal(owner, 'API_CLIENT', client['id'], frozenset(client['scopes']),
                             client['all_agents'], grants)
        return Principal(owner, 'SESSION', str(owner), SCOPES, True, frozenset())

    def tick(self, batch_size=100):
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise EngineError('invalid_batch_size')
        report = {'queued': [], 'failed': [], 'scheduled': [], 'ready_for_delivery': [], 'expired_pending': []}
        # Close stale execution attempts, not the schedule or its latest good result.
        stale_before = self.now - timedelta(hours=48)
        stale = self.conn.execute(select(m.jobs).where(
            m.jobs.c.state.in_(['CREATED', 'SCHEDULED', 'QUEUED']),
            m.jobs.c.created_at <= stale_before).order_by(m.jobs.c.created_at, m.jobs.c.id)
            .limit(batch_size).with_for_update(skip_locked=True)).mappings().all()
        for old_job in stale:
            self._fail(old_job, 'PENDING_EXPIRED_48H')
            report['expired_pending'].append(old_job['id'])
        expired = self.conn.execute(select(m.jobs).where(m.jobs.c.state.in_(['CREATED', 'SCHEDULED', 'QUEUED']),
            m.jobs.c.deadline_at <= self.now).order_by(m.jobs.c.deadline_at, m.jobs.c.id)
            .limit(batch_size).with_for_update(skip_locked=True)).mappings().all()
        for row in expired:
            self._fail(row)
            report['failed'].append(row['id'])
        due = self.conn.execute(select(m.schedules).join(m.agents, and_(
            m.schedules.c.owner_id == m.agents.c.owner_id, m.schedules.c.agent_id == m.agents.c.id))
            .join(Usuario.__table__, Usuario.id == m.schedules.c.owner_id).where(
                m.schedules.c.enabled.is_(True), m.schedules.c.next_run_at <= self.now,
                m.agents.c.configuration_state == 'ENABLED', Usuario.activo.is_(True))
            .order_by(m.schedules.c.next_run_at, m.schedules.c.id).limit(batch_size)
            .with_for_update(skip_locked=True)).mappings().all()
        for row in due:
            self._run_schedule(row, report)
        pending = self.conn.execute(select(m.jobs).join(m.agents, and_(
            m.jobs.c.owner_id == m.agents.c.owner_id, m.jobs.c.agent_id == m.agents.c.id))
            .join(Usuario.__table__, Usuario.id == m.jobs.c.owner_id).where(
                m.jobs.c.state.in_(['CREATED', 'SCHEDULED']), m.jobs.c.execute_at <= self.now,
                m.agents.c.configuration_state == 'ENABLED', Usuario.activo.is_(True))
            .order_by(m.jobs.c.priority.desc(), m.jobs.c.execute_at, m.jobs.c.id)
            .limit(batch_size).with_for_update(skip_locked=True)).mappings().all()
        for row in pending:
            try:
                principal = self._scheduled_author({'owner_id': row['owner_id'], 'definition': {
                    'author': {'kind': 'API_CLIENT' if row['client_id'] else 'SESSION',
                               'actor_id': row['client_id'] or str(row['owner_id'])}}})
                agent=locked_agent(self.conn, principal, row['agent_id'])
                from .pause_control import pause_state
                if any(pause_state(self.conn,agent).values()):continue
                self._queue(row)
                report['queued'].append(row['id'])
            except EngineError as error:
                self._fail(row, error.code)
                report['failed'].append(row['id'])
        from .automatic_task_review import review_scheduled_tasks, deliver_reviewed_tasks
        review_scheduled_tasks(self,report,batch_size)
        self._authorize_deliveries(report, batch_size)
        deliver_reviewed_tasks(self,report,batch_size)
        self._deliver_informational(report, batch_size)
        return report

    def _run_schedule(self, row, report):
        try:
            with self.conn.begin_nested():
                principal = self._scheduled_author(row)
                agent=locked_agent(self.conn,principal,row['agent_id'])
                from .pause_control import pause_state
                if any(pause_state(self.conn,agent).values()):return
                if row['legacy_task_id'] is not None:
                    from .configured_task_repository import ConfiguredTaskRepository
                    tasks=ConfiguredTaskRepository(self.conn).rows(agent,row['legacy_task_id'])
                    if not tasks or not tasks[0]['habilitada'] or (tasks[0]['parametros'] or {}).get('_deleted_at'):
                        self.conn.execute(update(m.schedules).where(m.schedules.c.id==row['id'],
                            m.schedules.c.owner_id==row['owner_id']).values(enabled=False,next_run_at=None,revision=row['revision']+1))
                        return
                following = next_occurrence(row['definition'], self.now)
                changed = self.conn.execute(update(m.schedules).where(m.schedules.c.id == row['id'],
                    m.schedules.c.owner_id == row['owner_id'], m.schedules.c.revision == row['revision'])
                    .values(next_run_at=following, enabled=following is not None, revision=row['revision']+1)).rowcount
                if changed != 1:
                    return
                slot = row['next_run_at']
                body = {**row['definition']['request'], 'execute_at': iso(slot),
                        'deliver_not_before': iso(delivery_time(row['definition'], slot))}
                job, _ = self.submit(principal, row['agent_id'], body,
                    'schedule:'+row['id']+':'+iso(slot), schedule_id=row['id'], slot=slot)
                report['scheduled'].append(job['id'])
                if job['state'] == 'FAILED':
                    report['failed'].append(job['id'])
        except EngineError as error:
            principal = Principal(row['owner_id'], 'SYSTEM', 'dispatcher', SCOPES, True, frozenset())
            agent = locked_agent(self.conn, principal, row['agent_id'])
            # Advance the slot after a transient failure; never disable the recurring definition.
            # Keep a bounded error audit and try again at the next normal occurrence.
            following = next_occurrence(row['definition'], self.now)
            changed = self.conn.execute(update(m.schedules).where(m.schedules.c.id == row['id'],
                m.schedules.c.owner_id == row['owner_id'], m.schedules.c.revision == row['revision'])
                .values(next_run_at=following, enabled=following is not None, revision=row['revision']+1)).rowcount
            if changed:
                audit_agent(self.conn, principal, agent, 'SCHEDULE_RUN_FAILED',
                    {'schedule_id': row['id'], 'reason_code': error.code}, self.now)

    def _deliver_informational(self, report, limit):
        from .informational_delivery import REASON, eligible_result
        report['informational_delivered'] = []
        rows = self.conn.execute(select(m.jobs).join(Usuario.__table__, Usuario.id == m.jobs.c.owner_id)
            .where(m.jobs.c.state == 'REVIEWING', Usuario.activo.is_(True),
                (m.jobs.c.deliver_not_before.is_(None) | (m.jobs.c.deliver_not_before <= self.now)),
                or_(
                    (m.jobs.c.schedule_id.is_not(None) & m.jobs.c.legacy_task_id.is_not(None)),
                    select(m.tasks.c.id).where(m.tasks.c.owner_id == m.jobs.c.owner_id,
                        m.tasks.c.job_id == m.jobs.c.id, m.tasks.c.tool_id == 'dpia.amazon.search').exists()))
            .order_by(m.jobs.c.priority.desc(), m.jobs.c.id).limit(limit)
            .with_for_update(skip_locked=True)).mappings().all()
        for job in rows:
            result = eligible_result(self.conn, job)
            if result is None:
                continue
            self._transition(job, 'DELIVERED', reason=REASON)
            self.conn.execute(insert(m.deliveries).values(id=str(uuid4()), owner_id=job['owner_id'],
                job_id=job['id'], result_id=result['id'], state='DELIVERED', authorized_at=self.now,
                available_at=self.now, delivered_at=self.now))
            report['informational_delivered'].append(job['id'])

    def _authorize_deliveries(self, report, limit):
        approved = self.conn.execute(select(m.jobs).join(Usuario.__table__, Usuario.id == m.jobs.c.owner_id)
            .where(m.jobs.c.state == 'APPROVED', Usuario.activo.is_(True),
                   (m.jobs.c.deliver_not_before.is_(None) | (m.jobs.c.deliver_not_before <= self.now)))
            .order_by(m.jobs.c.priority.desc(), m.jobs.c.id).limit(limit)
            .with_for_update(skip_locked=True)).mappings().all()
        for row in approved:
            reviewed = select(m.reviews.c.id).where(m.reviews.c.owner_id == m.results.c.owner_id,
                m.reviews.c.job_id == m.results.c.job_id, m.reviews.c.result_id == m.results.c.id,
                m.reviews.c.decision == 'APPROVED').exists()
            result = self.conn.execute(select(m.results).where(m.results.c.owner_id == row['owner_id'],
                m.results.c.job_id == row['id'], m.results.c.approved_at <= self.now, reviewed)
                .order_by(m.results.c.version.desc()).limit(1)).mappings().first()
            if result:
                self._transition(row, 'READY_FOR_DELIVERY')
                self.conn.execute(insert(m.deliveries).values(id=str(uuid4()), owner_id=row['owner_id'],
                    job_id=row['id'], result_id=result['id'], state='PENDING', authorized_at=self.now,
                    available_at=self.now))
                report['ready_for_delivery'].append(row['id'])


def public_schedule(row):
    return {'id': row['id'], 'agent_id': row['agent_id'], 'legacy_task_id': row.get('legacy_task_id'), 'enabled': row['enabled'],
            'revision': row['revision'], 'timezone': row['timezone'], 'next_run_at': iso(row['next_run_at']),
            'configuration': {key: value for key, value in row['definition'].items()
                              if key not in ('request_hash', 'author')}}
