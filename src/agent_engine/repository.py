"""Read models scoped by owner AND per-client agent grants. No provider calls."""
from datetime import timedelta
from sqlalchemy import select, func, and_
from .auth import Principal, now_utc
from .contracts import iso, validate, RESULT
from .errors import EngineError
from . import models as m


def agent_access(principal: Principal, column=m.agents.c.id):
    return column.in_(principal.agent_ids) if not principal.all_agents else column.is_not(None)


def public_job(row) -> dict:
    return {key: row[key] for key in ('id', 'agent_id', 'state', 'revision', 'progress',
                                     'priority', 'correlation_id', 'error_code')} | {
        key: iso(row[key]) for key in ('created_at', 'updated_at', 'execute_at',
            'deliver_not_before', 'deadline_at', 'started_at', 'finished_at')}


class ReadRepository:
    def __init__(self, conn, principal: Principal):
        self.conn = conn
        self.principal = principal

    def agent_filter(self):
        return and_(m.agents.c.owner_id == self.principal.owner_id, agent_access(self.principal))

    def job_filter(self):
        return and_(m.jobs.c.owner_id == self.principal.owner_id,
                    agent_access(self.principal, m.jobs.c.agent_id))

    def agent(self, agent_id: str):
        row = self.conn.execute(select(m.agents).where(self.agent_filter(), m.agents.c.id == agent_id)).mappings().first()
        if row is None:
            raise EngineError('agent_not_found', 404)
        return row

    def job(self, job_id: str):
        row = self.conn.execute(select(m.jobs).where(self.job_filter(), m.jobs.c.id == job_id)).mappings().first()
        if row is None:
            raise EngineError('job_not_found', 404)
        return row

    def activity(self, agent_id: str, owner_id: int) -> str:
        states = set(self.conn.execute(select(m.jobs.c.state).where(
            m.jobs.c.owner_id == owner_id, m.jobs.c.agent_id == agent_id,
            m.jobs.c.state.not_in(['DELIVERED', 'FAILED', 'CANCELLED']))).scalars())
        if states & {'RUNNING', 'REVIEWING', 'CORRECTION_REQUIRED'}:
            return 'WORKING'
        return 'WAITING' if states else 'IDLE'

    def public_agent(self, row, *, configuration=False):
        from .pause_control import pause_state
        data = {key: row[key] for key in ('id', 'name', 'description', 'configuration_state', 'revision', 'timezone')}
        data.update(pause=pause_state(self.conn, row), activity_state=self.activity(row['id'], row['owner_id']),
                    created_at=iso(row['created_at']), updated_at=iso(row['updated_at']))
        if configuration:
            data.update(instructions=row['instructions'], limits=row['limits'],
                        search_parameters=row['search_parameters'],
                        capabilities=list(self.conn.execute(select(m.agent_capabilities.c.tool_id).where(
                            m.agent_capabilities.c.owner_id == row['owner_id'],
                            m.agent_capabilities.c.agent_id == row['id']).order_by(m.agent_capabilities.c.tool_id)).scalars()))
        return data

    def agents(self, limit: int, after: str | None):
        query = select(m.agents).where(self.agent_filter())
        if after:
            query = query.where(m.agents.c.id > after)
        rows = self.conn.execute(query.order_by(m.agents.c.id).limit(limit + 1)).mappings().all()
        return {'items': [self.public_agent(row) for row in rows[:limit]],
                'next_cursor': rows[limit - 1]['id'] if len(rows) > limit else None}

    def jobs(self, limit: int, after: str | None, agent_id=None, state=None):
        query = select(m.jobs).where(self.job_filter())
        if agent_id:
            self.agent(agent_id)
            query = query.where(m.jobs.c.agent_id == agent_id)
        if state:
            query = query.where(m.jobs.c.state == state)
        if after:
            query = query.where(m.jobs.c.id > after)
        rows = self.conn.execute(query.order_by(m.jobs.c.id).limit(limit + 1)).mappings().all()
        return {'items': [public_job(row) for row in rows[:limit]],
                'next_cursor': rows[limit - 1]['id'] if len(rows) > limit else None}

    def result(self, job_id: str):
        job = self.job(job_id)
        if job['state'] != 'DELIVERED':
            raise EngineError('result_not_delivered', 409)
        if job['deliver_not_before'] is not None and job['deliver_not_before'] > now_utc():
            raise EngineError('result_not_delivered', 409)
        approved_review = select(m.reviews.c.id).where(
            m.reviews.c.owner_id == m.results.c.owner_id, m.reviews.c.job_id == m.results.c.job_id,
            m.reviews.c.result_id == m.results.c.id, m.reviews.c.decision == 'APPROVED').exists()
        from sqlalchemy import or_
        from .informational_delivery import REASON, eligible_result
        informational_event = select(m.events.c.id).where(m.events.c.owner_id == self.principal.owner_id,
            m.events.c.job_id == job_id, m.events.c.sequence == job['revision'],
            m.events.c.type == 'DELIVERED', m.events.c.actor_type == 'SYSTEM',
            m.events.c.actor_id == 'dispatcher', m.events.c.reason_code == REASON).exists()
        delivery_policy = or_(
            and_(m.results.c.approved_at.is_not(None), m.results.c.approved_at <= now_utc(),
                 m.deliveries.c.authorized_at >= m.results.c.approved_at, approved_review),
            and_(m.results.c.approved_at.is_(None), m.results.c.evidence_status == 'UNVERIFIED',
                 m.deliveries.c.authorized_at >= m.results.c.created_at, informational_event))
        query = select(m.results).join(m.deliveries, and_(
            m.deliveries.c.owner_id == m.results.c.owner_id,
            m.deliveries.c.job_id == m.results.c.job_id,
            m.deliveries.c.result_id == m.results.c.id)).where(
                m.results.c.owner_id == self.principal.owner_id, m.results.c.job_id == job_id,
                m.deliveries.c.state == 'DELIVERED', m.deliveries.c.delivered_at.is_not(None),
                m.deliveries.c.delivered_at <= now_utc(), m.deliveries.c.authorized_at <= now_utc(),
                m.deliveries.c.delivered_at >= m.deliveries.c.available_at,
                m.deliveries.c.available_at <= now_utc(), delivery_policy).order_by(m.results.c.version.desc()).limit(1)
        row = self.conn.execute(query).mappings().first()
        if row is None or (row['approved_at'] is None and eligible_result(self.conn, job, row) is None):
            raise EngineError('result_not_delivered', 409)
        try:
            validate(RESULT, row['payload'])
        except EngineError:
            raise EngineError('stored_result_unavailable', 503) from None
        return {'job_id': job_id, 'version': row['version'], 'evidence_status': row['evidence_status'],
                'delivery_kind': 'INFORMATIONAL' if row['approved_at'] is None else 'APPROVED',
                'result': row['payload']}

    def events(self, job_id: str, after_sequence: int, limit: int):
        self.job(job_id)
        rows = self.conn.execute(select(m.events).where(m.events.c.owner_id == self.principal.owner_id,
            m.events.c.job_id == job_id, m.events.c.sequence > after_sequence).order_by(
                m.events.c.sequence).limit(limit + 1)).mappings().all()
        return {'items': [{key: row[key] for key in ('sequence', 'type', 'reason_code', 'correlation_id')} |
                          {'created_at': iso(row['created_at'])} for row in rows[:limit]],
                'next_sequence': rows[limit - 1]['sequence'] if len(rows) > limit else None}

    def metrics(self):
        counts = self.conn.execute(select(m.jobs.c.state, func.count().label('count')).where(
            self.job_filter()).group_by(m.jobs.c.state)).mappings().all()
        # Only provider-evidenced measurements; missing monetary data remains null.
        measured = self.conn.execute(select(m.usage.c.provider_id, m.usage.c.currency,
            func.sum(m.usage.c.calls).label('calls'), func.sum(m.usage.c.input_tokens).label('input_tokens'),
            func.sum(m.usage.c.output_tokens).label('output_tokens'), func.sum(m.usage.c.cost).label('cost')
        ).join(m.jobs, and_(m.usage.c.owner_id == m.jobs.c.owner_id, m.usage.c.job_id == m.jobs.c.id)
        ).where(self.job_filter(), m.usage.c.verified.is_(True),
                m.usage.c.evidence_source.in_(['PROVIDER_RESPONSE', 'PROVIDER_BILLING']))
        .group_by(m.usage.c.provider_id, m.usage.c.currency)).mappings().all()
        return {'jobs_by_state': {row['state']: row['count'] for row in counts},
                'usage_status': 'MEASURED' if measured else 'UNAVAILABLE',
                'provider_usage': [{**dict(row), 'cost': str(row['cost']) if row['cost'] is not None else None}
                                   for row in measured]}

    def admin_result(self, job_id: str):
        if not self.principal.admin or self.principal.kind != 'SESSION':
            raise EngineError('administrator_session_required', 403)
        owner_id = self.conn.execute(select(m.jobs.c.owner_id).where(m.jobs.c.id == job_id)).scalar_one_or_none()
        if owner_id is None:
            raise EngineError('job_not_found', 404)
        # Explicit administrator path; regular endpoints never broaden owner scope.
        restricted = Principal(owner_id, 'SESSION', self.principal.actor_id,
                               self.principal.scopes, True, frozenset())
        return ReadRepository(self.conn, restricted).result(job_id)

    def admin_overview(self):
        if not self.principal.admin or self.principal.kind != 'SESSION':
            raise EngineError('administrator_session_required', 403)
        agent_rows = self.conn.execute(select(m.agents).order_by(m.agents.c.updated_at.desc(), m.agents.c.id).limit(100)).mappings().all()
        job_rows = self.conn.execute(select(m.jobs).order_by(m.jobs.c.updated_at.desc(), m.jobs.c.id).limit(100)).mappings().all()
        worker_rows = self.conn.execute(select(m.workers).order_by(m.workers.c.id).limit(100)).mappings().all()
        now = now_utc()
        counts = self.conn.execute(select(m.jobs.c.state, func.count().label('count')).group_by(m.jobs.c.state)).mappings()
        counts = {row['state']: row['count'] for row in counts}
        attempt_counts = dict(self.conn.execute(select(m.tasks.c.job_id, func.sum(m.tasks.c.attempt_count))
            .where(m.tasks.c.job_id.in_([row['id'] for row in job_rows])).group_by(m.tasks.c.job_id)).all())
        measured = self.conn.execute(select(m.usage.c.provider_id, m.usage.c.currency,
            func.sum(m.usage.c.calls).label('calls'), func.sum(m.usage.c.input_tokens).label('input_tokens'),
            func.sum(m.usage.c.output_tokens).label('output_tokens'), func.sum(m.usage.c.cost).label('cost'))
            .where(m.usage.c.verified.is_(True), m.usage.c.evidence_source.in_(['PROVIDER_RESPONSE', 'PROVIDER_BILLING']))
            .group_by(m.usage.c.provider_id, m.usage.c.currency)).mappings().all()
        return {
            'agents': [self.public_agent(row) | {'owner_id': row['owner_id']} for row in agent_rows],
            'jobs': [public_job(row) | {'owner_id': row['owner_id'], 'attempt_count': attempt_counts.get(row['id'])} for row in job_rows],
            'workers': [{'id': row['id'], 'capabilities': row['capabilities'],
                         'availability': ('DISCONNECTED' if row['heartbeat_at'] is None or
                                          now - row['heartbeat_at'] > timedelta(seconds=60)
                                          else row['reported_state']),
                         'heartbeat_at': iso(row['heartbeat_at'])} for row in worker_rows],
            'jobs_by_state': counts,
            'provider_usage': [{**dict(row), 'cost': str(row['cost']) if row['cost'] is not None else None} for row in measured],
            'list_limit': 100,
        }
