"""At-least-once publication. Redis and MySQL are deliberately not a fake 2PC."""
from datetime import timedelta
from sqlalchemy import select, update, and_
from model.usuario import Usuario
from . import models as m
from .errors import EngineError
from .streams import TaskMessage


class OutboxPublisher:
    def __init__(self, box, streams):
        self.box, self.streams = box, streams

    def publish_batch(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise EngineError('invalid_batch_size')
        report = {'published': 0, 'unconfirmed': 0, 'rejected': 0}
        with self.box.engine.begin() as conn:
            rows = conn.execute(select(m.outbox).join(m.jobs, and_(
                m.jobs.c.owner_id == m.outbox.c.owner_id, m.jobs.c.id == m.outbox.c.job_id))
                .join(m.tasks, and_(m.tasks.c.owner_id == m.outbox.c.owner_id, m.tasks.c.id == m.outbox.c.task_id))
                .join(m.agents, and_(m.agents.c.owner_id == m.jobs.c.owner_id, m.agents.c.id == m.jobs.c.agent_id))
                .join(Usuario.__table__, Usuario.id == m.jobs.c.owner_id).where(
                    m.outbox.c.published_at.is_(None), m.outbox.c.available_at <= self.box.now(),
                    m.jobs.c.state.in_(['QUEUED', 'RUNNING']), m.tasks.c.state == 'PENDING',
                    m.tasks.c.provider_submission_state == 'NOT_SUBMITTED',
                    m.agents.c.configuration_state == 'ENABLED', Usuario.activo.is_(True))
                .order_by(m.jobs.c.priority.desc(), m.outbox.c.available_at, m.outbox.c.id)
                .limit(limit).with_for_update(skip_locked=True)).mappings().all()
            for row in rows:
                job = self.box._job(conn, row['owner_id'], row['job_id'])
                task = self.box._task(conn, row['owner_id'], row['task_id'])
                if job['deadline_at'] and job['deadline_at'] <= self.box.now():
                    self.box._fail(conn, job, 'JOB_DEADLINE_EXCEEDED')
                    report['rejected'] += 1
                    continue
                try:
                    spec = self.box.authorized(conn, job, task, require_provider=False)
                    if spec.capability != row['capability']:
                        raise EngineError('invalid_task_capability')
                except EngineError as error:
                    if error.code not in ('agent_paused', 'integration_disabled'):
                        self.box._fail(conn, job, error.code)
                        report['rejected'] += 1
                    continue
                try:
                    message_id = self.streams.publish(row['capability'],
                        TaskMessage(row['owner_id'], row['job_id'], row['task_id'], row['id']))
                except EngineError:
                    conn.execute(update(m.outbox).where(m.outbox.c.id == row['id'],
                        m.outbox.c.owner_id == row['owner_id']).values(attempt_count=row['attempt_count']+1,
                            available_at=self.box.now()+timedelta(seconds=min(60, 2**min(row['attempt_count']+1, 6)))))
                    report['unconfirmed'] += 1
                    continue
                conn.execute(update(m.outbox).where(m.outbox.c.owner_id == row['owner_id'],
                    m.outbox.c.id == row['id']).values(published_at=self.box.now(),
                        stream_message_id=message_id, attempt_count=row['attempt_count']+1))
                report['published'] += 1
        return report
