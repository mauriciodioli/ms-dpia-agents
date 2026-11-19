"""Eligibility for informational delivery; factual approval remains separate."""
from sqlalchemy import select
from . import models as m
from .contracts import RESULT, validate
from .errors import EngineError

REASON = 'INFORMATIONAL_UNVERIFIED'


def accepted_video(job):
    decision=(job.get('configuration_snapshot') or {}).get('manager_latest_decision') or {}
    return decision.get('reason')=='VIDEO_COMPLETED' and decision.get('decision')=='ACCEPT'


def eligible_result(conn, job, result=None):
    from .result_assessment import human_review_allows_delivery
    if not human_review_allows_delivery(job):return None
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
    early=any(value.get('reason') in ('STRUCTURED_JOB_OBJECTIVE_SATISFIED','STRUCTURED_COMMERCIAL_OBJECTIVE_SATISFIED','PARTIAL_JOB_RESULTS','SEARCH_NO_MATCH','MANAGER_SEMANTIC_REJECT','RESULT_OBJECTIVE_NOT_SATISFIED') for value in job['configuration_snapshot'].get('manager_decisions',{}).values())
    if early:tasks=[task for task in tasks if task['state']!='CANCELLED']
    # Unscheduled/mixed pipelines retain the existing review requirements.
    if (not tasks or any(t['state']!='COMPLETED' for t in tasks)
            or (not automatic and not early and (latest['evidence_status']!='UNVERIFIED' or any(t['tool_id']!='dpia.amazon.search' for t in tasks)))):
        return None
    if (automatic or early) and validation_reasons(conn,job,latest):return None
    from .result_consolidation import persisted_matches
    if not persisted_matches(job,tasks,latest['payload']):
        return None
    if conn.execute(select(m.reviews.c.id).where(m.reviews.c.owner_id == job['owner_id'],
            m.reviews.c.job_id == job['id'], m.reviews.c.result_id == latest['id'])).first():
        return None
    try:
        validate(RESULT, latest['payload'])
    except EngineError:
        return None
    return latest
