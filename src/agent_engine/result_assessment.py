"""Manager outcome and human feedback, separate from technical/evidence approval.

Stored in the existing job JSON; no result copies, schema changes or provider calls.
"""
from sqlalchemy import select, update
from . import models as m
from .auth import now_utc
from .contracts import iso
from .errors import EngineError

REVIEWABLE = frozenset({'PARTIAL', 'DIVERGENT', 'INSUFFICIENT_EVIDENCE'})
LABELS = {'SATISFIED':'Objetivo satisfecho', 'PARTIAL':'Resultado parcial',
          'DIVERGENT':'Resultado divergente', 'INSUFFICIENT_EVIDENCE':'Evidencia insuficiente',
          'NO_MATCH':'Sin coincidencias', 'TECHNICAL_ERROR':'Error técnico'}
REASONS = {'STRUCTURED_JOB_OBJECTIVE_SATISFIED':'Los resultados satisfacen los criterios laborales solicitados.',
           'STRUCTURED_COMMERCIAL_OBJECTIVE_SATISFIED':'Los resultados satisfacen los criterios comerciales solicitados.',
           'PARTIAL_JOB_RESULTS':'Hay resultados útiles, pero no cumplen todos los requisitos solicitados.',
           'SEARCH_NO_MATCH':'La búsqueda terminó sin coincidencias para los criterios solicitados.',
           'RESULT_OBJECTIVE_NOT_SATISFIED':'Los resultados no satisfacen los criterios de la solicitud.'}
ERRORS = {'DISPATCH_DEADLINE_EXCEEDED':'El trabajo no pudo iniciarse antes de su fecha u hora límite.',
          'JOB_DEADLINE_EXCEEDED':'La ejecución superó su fecha u hora límite.',
          'TASK_ATTEMPT_BUDGET_EXCEEDED':'Se agotó el límite de intentos permitido para completar la tarea.'}


def classification(job, payload):
    """Project the Manager's actual decision; never infer success from job status."""
    snapshot = job['configuration_snapshot']
    # MySQL JSON objects do not preserve insertion order of UUID/fingerprint keys.
    last = snapshot.get('manager_latest_decision', {})
    reason = last.get('reason', '')
    semantic = snapshot.get('manager_semantic_decision', {})
    if semantic.get('task_id') != last.get('task_id'):semantic = {}
    explanation = semantic.get('reason') if reason.startswith('MANAGER_SEMANTIC_') else None
    if reason == 'PARTIAL_JOB_RESULTS': category = 'PARTIAL'
    elif reason == 'SEARCH_NO_MATCH': category = 'NO_MATCH'
    elif reason in ('STRUCTURED_JOB_OBJECTIVE_SATISFIED','STRUCTURED_COMMERCIAL_OBJECTIVE_SATISFIED'):
        category = 'SATISFIED'
    elif reason == 'MANAGER_SEMANTIC_REJECT':
        category = 'INSUFFICIENT_EVIDENCE' if semantic.get('missing_information') else 'DIVERGENT'
    elif reason == 'RESULT_OBJECTIVE_NOT_SATISFIED' and payload.get('items'):
        category = 'DIVERGENT'
    else: category = 'INSUFFICIENT_EVIDENCE'
    return {'result_classification': category,
            'classification_reason': explanation or REASONS.get(reason, 'No hay una evaluación suficiente del cumplimiento del objetivo.'),
            'manager_decision':last.get('decision'), 'reason_code':reason or None,
            'requirements_pending':semantic.get('missing_information', []),
            'requirements_satisfied':[], 'review_required':category in REVIEWABLE}


def human_review_allows_delivery(job):
    assessment=job['configuration_snapshot'].get('result_assessment',{})
    if not assessment.get('review_required'):return True
    feedback=job['configuration_snapshot'].get('result_reviews',{}).get(assessment.get('result_id'),{})
    return feedback.get('decision')=='ACCEPTED'


def with_latest_decision(conn, job):
    snapshot=job['configuration_snapshot']
    if snapshot.get('manager_latest_decision'):return job
    decisions=snapshot.get('manager_decisions',{})
    ids=conn.execute(select(m.tasks.c.id).where(m.tasks.c.owner_id==job['owner_id'],m.tasks.c.job_id==job['id'])
                     .order_by(m.tasks.c.position.desc())).scalars() if decisions else []
    latest=next(({'task_id':key,**decisions[key]} for key in ids if key in decisions),{})
    return {**job,'configuration_snapshot':{**snapshot,'manager_latest_decision':latest}}


def persist(conn, job, result_id, payload):
    current = conn.execute(select(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])).mappings().one()
    current=with_latest_decision(conn,current)
    snapshot = dict(current['configuration_snapshot'])
    snapshot['result_assessment'] = {**classification(current, payload), 'result_id':result_id}
    conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id']).values(configuration_snapshot=snapshot))


def inspect(conn, job):
    result = conn.execute(select(m.results).where(m.results.c.owner_id==job['owner_id'],m.results.c.job_id==job['id'])
                          .order_by(m.results.c.version.desc()).limit(1)).mappings().first()
    job=with_latest_decision(conn,job)
    snapshot = job['configuration_snapshot']
    assessment = snapshot.get('result_assessment')
    if job['state']=='FAILED':
        assessment = {'result_classification':'TECHNICAL_ERROR','classification_reason':ERRORS.get(job['error_code'],'La ejecución falló; consultá el código técnico.'),
                      'manager_decision':snapshot.get('manager_latest_decision',{}).get('decision'),'review_required':False}
    elif result is None: assessment = {'result_classification':None,'classification_reason':'Todavía no hay un resultado final.', 'manager_decision':None,'review_required':False}
    elif not assessment or assessment.get('result_id')!=result['id']:
        # Historical results are shown without manufacturing a new persisted decision.
        assessment = classification(job, result['payload']) if snapshot.get('manager_decisions') else {
            'result_classification':None,'classification_reason':'Resultado histórico sin clasificación registrada.',
            'manager_decision':None,'review_required':False}
    review = snapshot.get('result_reviews', {}).get(result['id'], {}) if result else {}
    required = bool(assessment.get('review_required')) and job['state']!='FAILED' and result is not None
    return {**assessment,'job_status':job['state'], 'job_id':job['id'],
            'result_id':result['id'] if result else None, 'evidence_status':result['evidence_status'] if result else None,
            'objective':job['request_snapshot'].get('objective') or job['request_snapshot'].get('instructions',''),
            'review_status':review.get('decision', 'PENDING_REVIEW' if required else 'NOT_REQUIRED'),
            'review_required':required and not bool(review),'reviewed_at':review.get('reviewed_at'),'reviewed_by':review.get('reviewed_by'),
            'review_reason':review.get('reason',''), 'review_history':sorted(snapshot.get('result_reviews',{}).values(),key=lambda entry:(entry.get('reviewed_at',''),entry.get('result_id',''))),
            'result':result['payload'] if result and job['state']!='FAILED' else None,
            'evidence':result['payload'].get('sources',[]) if result and job['state']!='FAILED' else [],
            'error_code':job['error_code'], 'error_message':ERRORS.get(job['error_code'],'La ejecución falló; consultá el código técnico.') if job['error_code'] else None}


def review(conn, principal, job_id, result_id, decision, reason=''):
    from .repository import ReadRepository
    from .management import audit_agent
    principal.require('results:review');principal.require('results:read')
    ReadRepository(conn, principal).job(job_id)
    if decision not in ('ACCEPTED','REJECTED') or not isinstance(reason,str) or len(reason)>1000:
        raise EngineError('invalid_result_feedback')
    job = conn.execute(select(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==principal.owner_id).with_for_update()).mappings().one()
    state = inspect(conn,job)
    if state['result_id'] != result_id: raise EngineError('stale_review_result',409)
    previous = job['configuration_snapshot'].get('result_reviews',{}).get(result_id)
    if previous:
        if previous['decision']!=decision or previous['reason']!=reason.strip():raise EngineError('result_feedback_conflict',409)
        return state
    if not state['review_required']: raise EngineError('result_feedback_not_allowed',409)
    entry = {'result_id':result_id,'decision':decision,'reason':reason.strip(),
             'reviewed_at':iso(now_utc()),'reviewed_by':str(principal.owner_id),
             'review_actor':{'type':principal.kind,'id':principal.actor_id}}
    snapshot=dict(job['configuration_snapshot']);reviews=dict(snapshot.get('result_reviews',{}));reviews[result_id]=entry;snapshot['result_reviews']=reviews
    conn.execute(update(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==principal.owner_id).values(configuration_snapshot=snapshot))
    agent=ReadRepository(conn,principal).agent(job['agent_id'])
    audit_agent(conn,principal,agent,'RESULT_USER_FEEDBACK',{'job_id':job_id,**entry})
    return inspect(conn,{**job,'configuration_snapshot':snapshot})


def previous_feedback(conn, job):
    """Only the same configured task/schedule, never unrelated tasks of an agent."""
    if not job.get('legacy_task_id') and not job.get('schedule_id'):return []
    match = m.jobs.c.legacy_task_id==job['legacy_task_id'] if job.get('legacy_task_id') else m.jobs.c.schedule_id==job['schedule_id']
    rows=conn.execute(select(m.jobs.c.id,m.jobs.c.configuration_snapshot).where(m.jobs.c.owner_id==job['owner_id'],
        m.jobs.c.agent_id==job['agent_id'],m.jobs.c.id!=job['id'],m.jobs.c.created_at<=job['created_at'],match,
        m.jobs.c.configuration_snapshot['result_reviews'].as_string().is_not(None))
        .order_by(m.jobs.c.created_at.desc(),m.jobs.c.id.desc()).limit(5)).mappings().all()
    return [{'job_id':row['id'],**feedback} for row in rows for feedback in row['configuration_snapshot'].get('result_reviews',{}).values()]


def remove_no_match(conn,principal,job):
    principal.require('agents:write')
    from sqlalchemy import select,update
    from . import models as m
    from .auth import now_utc
    from .contracts import iso
    from .configured_tasks import ConfiguredTaskManager
    from .management import audit_agent
    if inspect(conn,job)['result_classification'] not in {'PARTIAL','DIVERGENT','INSUFFICIENT_EVIDENCE','NO_MATCH','TECHNICAL_ERROR'} or not job['legacy_task_id']:
        raise EngineError('no_match_task_required',409)
    service=ConfiguredTaskManager(conn,principal);_,agent=service.access(job['agent_id'])
    rows=service.repository.rows(agent,job['legacy_task_id'])
    if not rows:raise EngineError('task_not_found',404)
    row=rows[0];params=dict(row['parametros'] or {})
    if params.get('_deleted_at'):return {'removed':True}
    active=conn.execute(select(m.jobs.c.id).where(m.jobs.c.owner_id==principal.owner_id,
        m.jobs.c.agent_id==job['agent_id'],m.jobs.c.legacy_task_id==job['legacy_task_id'],m.jobs.c.id!=job['id'],
        m.jobs.c.state.not_in(['FAILED','CANCELLED','DELIVERED'])).with_for_update()).first()
    if active:raise EngineError('task_has_active_executions',409)
    params['_deleted_at']=iso(now_utc())
    service.repository.save(row,name=row['nombre'],parameters=params,now=now_utc())
    table=service.repository.table()
    conn.execute(update(table).where(table.c.id==row['id'],table.c.agente_id==row['agente_id']).values(habilitada=False))
    conn.execute(update(m.schedules).where(m.schedules.c.owner_id==principal.owner_id,
        m.schedules.c.agent_id==job['agent_id'],m.schedules.c.legacy_task_id==row['id']).values(enabled=False))
    audit_agent(conn,principal,agent,'TASK_DELETED_NO_MATCH' if inspect(conn,job)['result_classification']=='NO_MATCH' else 'TASK_DELETED_FROM_RESULT',{'task_id':row['id'],'job_id':job['id']})
    return {'removed':True}
