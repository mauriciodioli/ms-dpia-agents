"""Eligibility for informational delivery; factual approval remains separate."""
from sqlalchemy import select
from . import models as m
from .contracts import RESULT, validate
from .errors import EngineError

REASON = 'INFORMATIONAL_UNVERIFIED'


def eligible_result(conn, job, result=None):
    latest = conn.execute(select(m.results).where(m.results.c.owner_id == job['owner_id'],
        m.results.c.job_id == job['id']).order_by(m.results.c.version.desc()).limit(1)).mappings().first()
    if latest is None or (result is not None and result['id'] != latest['id']):
        return None
    if latest['evidence_status'] not in ('UNVERIFIED','SOURCE_REFERENCED') or latest['approved_at'] is not None:
        return None
    tasks = conn.execute(select(m.tasks).where(m.tasks.c.owner_id == job['owner_id'],
        m.tasks.c.job_id == job['id']).order_by(m.tasks.c.position)).mappings().all()
    from .automatic_task_review import automatic_task, validation_reasons
    automatic=automatic_task(conn,job)
    # Unscheduled/mixed pipelines retain the existing review requirements.
    if (not tasks or any(t['state']!='COMPLETED' for t in tasks)
            or (not automatic and (latest['evidence_status']!='UNVERIFIED' or any(t['tool_id']!='dpia.amazon.search' for t in tasks)))):
        return None
    if automatic and validation_reasons(conn,job,latest):return None
    if tasks[-1]['output'] != latest['payload']:
        return None
    if conn.execute(select(m.reviews.c.id).where(m.reviews.c.owner_id == job['owner_id'],
            m.reviews.c.job_id == job['id'], m.reviews.c.result_id == latest['id'])).first():
        return None
    try:
        validate(RESULT, latest['payload'])
    except EngineError:
        return None
    return latest
