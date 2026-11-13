"""Deterministic review of scheduled configured tasks. Never asserts factual verification."""
from sqlalchemy import select, update
from . import models as m
from .contracts import RESULT, validate
from .errors import EngineError
from .verifier import inspect_output
from .reviewer import Reviewer
from .management import audit_agent
from .auth import Principal, SCOPES


def automatic_task(conn, job):
    if job['schedule_id'] is None or job['legacy_task_id'] is None:
        return False
    return conn.execute(select(m.schedules.c.id).where(
        m.schedules.c.owner_id==job['owner_id'], m.schedules.c.agent_id==job['agent_id'],
        m.schedules.c.id==job['schedule_id'],m.schedules.c.legacy_task_id==job['legacy_task_id'])).first() is not None


def validation_reasons(conn, job, result):
    reasons=list(inspect_output(result['payload'],result['schema_version'])['reason_codes'])
    try:validate(RESULT,result['payload'])
    except EngineError:reasons.append('INVALID_RESULT_CONTRACT')
    tasks=conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
        m.tasks.c.job_id==job['id']).order_by(m.tasks.c.position)).mappings().all()
    if not tasks or any(task['state']!='COMPLETED' for task in tasks):
        reasons.append('INCOMPLETE_TASK_PIPELINE')
    elif tasks[-1]['output']!=result['payload']:
        reasons.append('RESULT_OUTPUT_MISMATCH')
    return reasons


def review_scheduled_tasks(dispatcher, report, limit):
    from model.usuario import Usuario
    conn=dispatcher.conn
    report['automatically_reviewed']=[]
    jobs=conn.execute(select(m.jobs).join(Usuario.__table__,Usuario.id==m.jobs.c.owner_id).where(
        m.jobs.c.state=='REVIEWING',m.jobs.c.schedule_id.is_not(None),m.jobs.c.legacy_task_id.is_not(None),
        Usuario.activo.is_(True)).order_by(m.jobs.c.id).limit(limit).with_for_update(skip_locked=True)).mappings().all()
    for job in jobs:
        if not automatic_task(conn,job):continue
        result=conn.execute(select(m.results).where(m.results.c.owner_id==job['owner_id'],
            m.results.c.job_id==job['id']).order_by(m.results.c.version.desc()).limit(1)).mappings().first()
        if result is None:
            dispatcher._fail(job,'AUTOMATIC_REVIEW_RESULT_MISSING');report['failed'].append(job['id']);continue
        # Never override a decision already recorded for this result.
        if conn.execute(select(m.reviews.c.id).where(m.reviews.c.owner_id==job['owner_id'],
                m.reviews.c.job_id==job['id'],m.reviews.c.result_id==result['id'])).first():continue
        reasons=validation_reasons(conn,job,result)
        if reasons:
            Reviewer(conn,now=dispatcher.now).review(owner_id=job['owner_id'],job_id=job['id'],
                result_id=result['id'],expected_revision=job['revision'],decision='REJECTED',
                reason_codes=reasons,actor_id='automatic-task-review')
            report['failed'].append(job['id'])
        elif result['evidence_status']=='VERIFIED':
            Reviewer(conn,now=dispatcher.now).review(owner_id=job['owner_id'],job_id=job['id'],
                result_id=result['id'],expected_revision=job['revision'],decision='APPROVED',
                reason_codes=[],actor_id='automatic-task-review')
        recorded=conn.execute(select(m.agent_events.c.id).where(m.agent_events.c.owner_id==job['owner_id'],
            m.agent_events.c.agent_id==job['agent_id'],m.agent_events.c.action=='AUTOMATIC_TASK_REVIEW_COMPLETED',
            m.agent_events.c.details['result_id'].as_string()==result['id'])).first()
        if not recorded:
            principal=Principal(job['owner_id'],'SYSTEM','automatic-task-review',SCOPES,True,frozenset())
            agent=conn.execute(select(m.agents).where(m.agents.c.owner_id==job['owner_id'],m.agents.c.id==job['agent_id'])).mappings().one()
            audit_agent(conn,principal,agent,'AUTOMATIC_TASK_REVIEW_COMPLETED',
                {'job_id':job['id'],'result_id':result['id'],'accepted':not reasons,
                 'evidence_status':result['evidence_status'],'reason_codes':reasons},dispatcher.now)
            report['automatically_reviewed'].append(job['id'])


def deliver_reviewed_tasks(dispatcher, report, limit):
    """Finish previously verified, automatically approved tasks using the delivery ledger."""
    from model.usuario import Usuario
    conn=dispatcher.conn;report['automatically_delivered']=[]
    rows=conn.execute(select(m.jobs).join(Usuario.__table__,Usuario.id==m.jobs.c.owner_id).where(m.jobs.c.state=='READY_FOR_DELIVERY',
        m.jobs.c.schedule_id.is_not(None),m.jobs.c.legacy_task_id.is_not(None),Usuario.activo.is_(True))
        .order_by(m.jobs.c.id).limit(limit).with_for_update(skip_locked=True)).mappings().all()
    for job in rows:
        if not automatic_task(conn,job):continue
        delivery=conn.execute(select(m.deliveries).where(m.deliveries.c.owner_id==job['owner_id'],
            m.deliveries.c.job_id==job['id'],m.deliveries.c.state=='PENDING',
            m.deliveries.c.available_at<=dispatcher.now)).mappings().first()
        if delivery is None:continue
        result=conn.execute(select(m.results).where(m.results.c.owner_id==job['owner_id'],m.results.c.job_id==job['id'],m.results.c.id==delivery['result_id'])).mappings().one()
        if validation_reasons(conn,job,result):
            dispatcher._fail(job,'AUTOMATIC_DELIVERY_INVALID_RESULT');report['failed'].append(job['id']);continue
        dispatcher._transition(job,'DELIVERED',reason='AUTOMATIC_TASK_REVIEW_APPROVED')
        conn.execute(update(m.deliveries).where(m.deliveries.c.id==delivery['id'],
            m.deliveries.c.owner_id==job['owner_id']).values(state='DELIVERED',delivered_at=dispatcher.now))
        report['automatically_delivered'].append(job['id'])
