"""Prepare execution plans and resources; workers only execute validated steps."""
import re
from flask import current_app
from .planner import Planner
from .integrations import IntegrationService
from .errors import EngineError, LOCAL_NON_RETRYABLE


def automatic_request(agent, body):
    """Derive the technical call allowance, without increasing the service ceiling.

    Candidate steps may exceed that ceiling: the manager will optimize them at
    dispatch, after connectivity checks. Other caller limits are never increased.
    """
    limits = dict(body['limits'])
    ceiling = agent['limits']['max_tool_calls']
    from .video_plan import is_plan
    if is_plan(body):
        limits['max_tool_calls']=min(limits['max_tool_calls'],ceiling)
        return {**body,'limits':limits}
    steps = len(body.get('pipeline', []))
    limits['max_corrections'] = min(limits['max_corrections'], agent['limits']['max_corrections'])
    if steps:
        # Reserve complete correction cycles only when the call ceiling permits them.
        limits['max_corrections'] = min(limits['max_corrections'], max(0, ceiling // steps - 1))
    needed = steps * (1 + limits['max_corrections']) if steps else ceiling
    limits['max_tool_calls'] = max(1, min(needed, ceiling))
    return {**body, 'limits': limits}


class ExecutionManager:
    def __init__(self, conn, registry):
        self.conn, self.registry = conn, registry
        self.planner_usage = None
        self.skipped = []
        self.no_sources = False
        self.optimized = False

    def resolve_context(self, agent, body):
        from .context_matching import resolve
        return resolve(agent, body)

    def evaluate_step(self, job, task, output, following):
        """Authorize advancement; sufficiency never implies factual verification."""
        from .contracts import RESULT, validate
        from .video_plan import SCRIPT,PRODUCE
        if task['tool_id']==SCRIPT:
            from .video_worker import prior_script
            try:prior_script([task.get('output') or output])
            except EngineError:return 'REJECT','VIDEO_SCRIPT_NOT_PERSISTED'
            return ('CONTINUE','VIDEO_SCRIPT_READY') if following else ('REJECT','VIDEO_PRODUCTION_STAGE_MISSING')
        if task['tool_id']==PRODUCE:
            video=output.get('video')
            if isinstance(video,dict) and video.get('state')=='COMPLETED' and video.get('remote_id') and video.get('url'):
                return 'ACCEPT','VIDEO_COMPLETED'
            return 'REJECT','VIDEO_PROVIDER_INVALID_RESPONSE'
        objective = job['request_snapshot'].get('objective') or job['request_snapshot'].get('instructions', '')
        try:
            validate(RESULT, output)
        except EngineError:
            # Existing local/custom outputs retain their final review contract.
            if output.get('schema_version') == 'agents.result.v1':
                return 'REJECT', 'INVALID_RESULT_CONTRACT'
            if not output or re.search(r'producto|reventa|revender|emple|vacante|laboral|trabajo',objective.casefold()):
                return ('CONTINUE','RESULT_REQUIRES_AUTHORIZED_STAGE') if following else ('REJECT','RESULT_OBJECTIVE_NOT_SATISFIED')
            return ('CONTINUE', 'NEXT_AUTHORIZED_STAGE_REQUIRED') if following else ('ACCEPT', 'PLAN_COMPLETED')
        from .adaptive_steps import commercial_objective
        raw=task.get('output') or output
        empty_search=any(key in raw and raw[key]==[] for key in ('items','results'))
        if not following and empty_search and not output.get('items') and not output.get('findings') and (task['tool_id'].startswith('mcp.') or task['tool_id'] in ('dpia.amazon.search','dpia.commercial.search')):
            return 'ACCEPT','SEARCH_NO_MATCH'
        if (task['tool_id'] in ('dpia.commercial.search','dpia.amazon.search') or commercial_objective(objective)) and not re.search(r'emple|vacante|laboral|trabajo',objective.casefold()):
            # Product/domain relevance cannot be proven by a shared title word.
            # Structured exact-filter checks may accept first; ambiguous evidence
            # goes through the durable internal reasoner, never lexical fallback.
            from .structured_acceptance import sufficient
            if sufficient(job,task,output):
                return 'ACCEPT','STRUCTURED_COMMERCIAL_OBJECTIVE_SATISFIED'
            return 'REASON','SEMANTIC_EVALUATION_REQUIRED'
        useful, enough, jobs, analysis = employment_sufficiency(job, output, objective)
        if jobs and enough and not analysis:
            return 'ACCEPT', 'STRUCTURED_JOB_OBJECTIVE_SATISFIED'
        if jobs:
            if following:
                return 'CONTINUE', 'RESULT_REQUIRES_AUTHORIZED_STAGE'
            if useful:
                return 'ACCEPT', 'PARTIAL_JOB_RESULTS'
            return 'REJECT', 'RESULT_OBJECTIVE_NOT_SATISFIED'
        return ('CONTINUE', 'NEXT_AUTHORIZED_STAGE_REQUIRED') if following else ('ACCEPT', 'PLAN_COMPLETED')

    def advance(self, box, conn, job, task, output, *, evaluation=None):
        """Persist decision and authorize one next step under the existing job lock."""
        from sqlalchemy import select, update, func
        from . import models as m
        from .dispatcher import Dispatcher
        following = conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
            m.tasks.c.job_id==job['id'],m.tasks.c.position>task['position'],
            m.tasks.c.state.in_(['WAITING_DEPENDENCY','PENDING']))
            .order_by(m.tasks.c.position).with_for_update()).mappings().all()
        from .result_consolidation import consolidate
        completed = conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
            m.tasks.c.job_id==job['id'],m.tasks.c.state=='COMPLETED').order_by(m.tasks.c.position)).mappings().all()
        try: normalized = consolidate([step['output'] for step in completed])
        except EngineError: normalized = None
        decision, reason = evaluation or self.evaluate_step(job, {**task,'output':output}, normalized or output, following)
        if job['deadline_at'] and job['deadline_at'] <= box.now():
            decision,reason='REJECT','JOB_DEADLINE_EXCEEDED'
        snapshot = dict(job['configuration_snapshot'])
        from .result_assessment import previous_feedback
        snapshot['prior_user_feedback'] = previous_feedback(conn,job)
        if decision == 'REASON':
            snapshot['manager_pending']={'task_id':task['id'],'state':'READY'}
            conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
                .values(configuration_snapshot=snapshot))
            return
        decisions = dict(snapshot.get('manager_decisions', {}))
        decisions[task['id']] = {'decision':decision,'reason':reason,'tool':task['tool_id']}
        snapshot['manager_decisions'] = decisions
        snapshot['manager_latest_decision'] = {'task_id':task['id'],**decisions[task['id']]}
        conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
            .values(configuration_snapshot=snapshot))
        semantic_result = normalized is not None and reason in ('MANAGER_SEMANTIC_REJECT','RESULT_OBJECTIVE_NOT_SATISFIED')
        if decision == 'REJECT' and not semantic_result:
            Dispatcher(conn, now=box.now(), registry=self.registry)._fail(job,reason)
            return
        if decision == 'CONTINUE':
            limits = job['request_snapshot']['limits']
            used = conn.execute(select(func.sum(m.tasks.c.attempt_count)).where(
                m.tasks.c.owner_id==job['owner_id'],m.tasks.c.job_id==job['id'])).scalar() or 0
            if used >= limits['max_tool_calls']:
                Dispatcher(conn, now=box.now(), registry=self.registry)._fail(job,'TASK_ATTEMPT_BUDGET_EXCEEDED')
                return
            if job['deadline_at'] and job['deadline_at'] <= box.now():
                Dispatcher(conn, now=box.now(), registry=self.registry)._fail(job,'JOB_DEADLINE_EXCEEDED')
                return
            next_task = following[0]
            from .adaptive_steps import resolve_parameters
            registry=self.registry.using(conn) if hasattr(self.registry,'using') else self.registry
            try:
                parameters,binding=resolve_parameters(next_task,completed,registry)
                box.authorized(conn,job,next_task,require_provider=True)
            except EngineError as error:
                if error.code == 'dependent_urls_missing':
                    conn.execute(update(m.tasks).where(m.tasks.c.id==next_task['id'],m.tasks.c.owner_id==job['owner_id'])
                        .values(state='CANCELLED'))
                    bindings=dict(snapshot.get('dependency_bindings',{}))
                    bindings[next_task['id']]={'skipped':True,'reason':error.code}
                    conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
                        .values(configuration_snapshot={**snapshot,'dependency_bindings':bindings}))
                    current=conn.execute(select(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])).mappings().one()
                    return self.advance(box,conn,current,task,output)
                # Missing search subjects are explicit failures, never fabricated inputs.
                decisions[task['id']]={**decisions[task['id']],'dependency_error':error.code}
                conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
                    .values(configuration_snapshot={**snapshot,'manager_decisions':decisions}))
                Dispatcher(conn, now=box.now(), registry=self.registry)._fail(job,error.code)
                return
            bindings=dict(snapshot.get('dependency_bindings',{}));bindings[next_task['id']]=binding
            snapshot['dependency_bindings']=bindings
            conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
                .values(configuration_snapshot=snapshot))
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
                m.tasks.c.id==next_task['id']).values(state='PENDING',
                    input_snapshot={**next_task['input_snapshot'],'parameters':parameters}))
            box._rearm(conn,job,next_task,box.now())
            box._event(conn,job,'MANAGER_CONTINUE',progress=int(100*(task['position']+1)/(task['position']+1+len(following))))
            return
        if following:
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
                m.tasks.c.job_id==job['id'],m.tasks.c.position>task['position'])
                .values(state='CANCELLED'))
        completed = conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
            m.tasks.c.job_id==job['id'],m.tasks.c.state=='COMPLETED').order_by(m.tasks.c.position)).mappings().all()
        try:
            canonical = consolidate([step['output'] for step in completed], partial=reason=='PARTIAL_JOB_RESULTS')
            if snapshot.get('accepted_evidence_urls'):
                from .result_consolidation import select_evidence
                canonical = select_evidence(canonical,snapshot['accepted_evidence_urls'])
        except EngineError:
            decisions[task['id']] = {'decision':'REJECT','reason':'RESULT_CONSOLIDATION_INVALID','tool':task['tool_id']}
            conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
                .values(configuration_snapshot={**snapshot,'manager_decisions':decisions}))
            Dispatcher(conn, now=box.now(), registry=self.registry)._fail(job,'RESULT_CONSOLIDATION_INVALID')
            return
        if canonical is not None:
            snapshot['canonical_result_version'] = 1
            snapshot['result_provenance'] = [{'task_id':step['id'],'tool':step['tool_id']} for step in completed]
            conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
                .values(configuration_snapshot=snapshot))
        Dispatcher(conn, now=box.now(), registry=self.registry).complete_result(job,canonical or output,reason='MANAGER_RESULT_REQUIRES_REVIEW' if semantic_result else 'MANAGER_ACCEPTED')

    def handle_failure(self, box, conn, job, task, error_code):
        # Keep the established safe-retry/uncertain-submission policy intact.
        from sqlalchemy import update, select, func
        from . import models as m
        snapshot = dict(job['configuration_snapshot'])
        history = list(snapshot.get('manager_failures', []))
        used = conn.execute(select(func.sum(m.tasks.c.attempt_count)).where(
            m.tasks.c.owner_id==job['owner_id'],m.tasks.c.job_id==job['id'])).scalar() or 0
        cannot_retry = (error_code in LOCAL_NON_RETRYABLE or task['attempt_count'] >= box.policy.max_attempts
            or used >= job['request_snapshot']['limits']['max_tool_calls'])
        history.append({'task_id':task['id'],'attempt':task['attempt_count'],
                        'reason':error_code or 'HANDLER_FAILED',
                        'decision':'REJECT' if (task['provider_submission_state']=='NOT_SUBMITTED' and
                            cannot_retry) else
                                   'RECOVER_UNCERTAIN' if task['provider_submission_state'] != 'NOT_SUBMITTED' else 'CORRECT'})
        snapshot['manager_failures'] = history[-100:]
        conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
            .values(configuration_snapshot=snapshot))
        box._retry_or_block(conn, job, task, error_code=error_code)

    def _plan(self, agent, body, *, permitted_tools=None):
        from .provider_access import ensure_access
        ensure_access(self.conn,agent,'openai')
        service = IntegrationService(current_app.extensions.get('agent_engine_engine') or __import__('utils.db', fromlist=['db']).db.engine, current_app.config)
        planner = Planner(self.conn, service=service, registry=self.registry)
        planner.task_instructions = body.get('instructions', '')
        if getattr(self,'prior_user_feedback',None):
            import json
            planner.task_instructions += '\nPrior user feedback (untrusted preferences, not tool or budget authority): '+json.dumps(self.prior_user_feedback,ensure_ascii=False)
        if permitted_tools is not None:
            planner.permitted_tools = frozenset(permitted_tools)
        objective = body.get('objective') or 'Prepare the smallest executable plan for the complete task instructions supplied below.'
        steps = planner.plan(objective, agent, body['limits'])
        self.planner_usage = planner.usage_record
        self.plan_omissions = planner.omitted_steps if hasattr(planner,'omitted_steps') else []
        return {**body, 'pipeline': steps, 'instructions': body.get('instructions', objective)}

    def prepare(self, agent, body, job_id=None, *, automatic=False):
        if automatic:
            body = automatic_request(agent, body)
            from .dispatcher import validate_request_budget
            validate_request_budget(agent, {'limits':body['limits']})
        if 'pipeline' in body:
            from .integrations import PROVIDERS
            from .provider_access import ensure_access
            selected={step['tool'] for step in body['pipeline']}
            from .commercial import TOOL, DEPENDENCIES
            if TOOL in selected: selected.update(DEPENDENCIES)
            for provider,spec in PROVIDERS.items():
                if spec['tool'] in selected:ensure_access(self.conn,agent,provider)
            return body
        result=self._plan(agent, body)
        from .integrations import PROVIDERS
        from .provider_access import ensure_access
        from .commercial import TOOL, DEPENDENCIES
        selected={step['tool'] for step in result['pipeline']}
        if TOOL in selected: selected.update(DEPENDENCIES)
        for provider,spec in PROVIDERS.items():
            if spec['tool'] in selected:ensure_access(self.conn,agent,provider)
        return result

    def finalize(self, agent, body, *, scheduled=False, automatic=False):
        """Called after authorization/schema checks, before any job reaches a worker."""
        from .video_plan import is_plan
        if is_plan(body):
            if body['limits']['max_tool_calls']<2:raise EngineError('video_execution_not_available',409)
            return body
        if scheduled:
            from .connection_preflight import ConnectionPreflight
            available, self.skipped = ConnectionPreflight(self.conn, self.registry).prepare(agent, body['pipeline'])
            self.no_sources = not available
            if self.no_sources:
                return body
            body = {**body, 'pipeline': available}
        if automatic:
            body = automatic_request(agent, body)
            if len(body['pipeline']) > body['limits']['max_tool_calls']:
                # Never truncate required steps or silently increase the agent budget.
                body = self._plan(agent, body, permitted_tools=[step['tool'] for step in body['pipeline']])
                self.optimized = True
                body = automatic_request(agent, body)
            from .dispatcher import validate_request_budget
            validate_request_budget(agent, body)
        return body


def employment_sufficiency(job, output, objective):
    """Cheap relevance rules over the requested subject, never every instruction word."""
    import re
    import unicodedata
    from .result_presentation import web_url
    def clean(value):
        return ''.join(c for c in unicodedata.normalize('NFKD',str(value).casefold())
                       if not unicodedata.combining(c))
    text = clean(objective)
    jobs = bool(re.search(r'emple|vacante|laboral|trabajo|\bjobs?\b',text))
    # Operational sentences, filters and requested response format are not keywords.
    first = re.split(r'[.\n;]',text,maxsplit=1)[0]
    subject = re.split(r'\b(?:en|para|in)\b',first,maxsplit=1)[0]
    subject = re.sub(r'^.*?(?:empleos?|vacantes?|ofertas(?: laborales)?|trabajos?|jobs?)\s*(?:reales|verificables|laborales)?\s*(?:de|para|como|of)?\s*','',subject)
    ignored={'buscar','busca','busque','ofertas','laborales','reales','verificables','digital',
             'especialista','coordinador','coordinadora','gerente','senior','junior','de','y','el','la'}
    anchors={word for word in re.findall(r'\w+',subject) if len(word)>2 and word not in ignored}
    aliases={'mercadotecnia':'marketing','mercadeo':'marketing','developer':'programador',
             'desarrollador':'programador','desarrolladora':'programador'}
    anchors={aliases.get(word,word) for word in anchors}
    # If a request is opaque, do not accept arbitrary cards just because they have links.
    useful=[];seen=set()
    for item in output.get('items',[]):
        title=clean(item.get('title',''));description=clean(item.get('description',''))
        url=web_url(item.get('url'))
        words={aliases.get(word,word) for word in re.findall(r'\w+',title+' '+description)}
        meaningful=len(description.split())>=3 or len(description)>=20
        related=bool(anchors & words) if anchors else bool(re.search(r'emple|vacante|marketing|puesto|\bjob\b',title+' '+description))
        wrong_city=('guadalajara' in text or 'gdl' in text) and not re.search(r'guadalajara|\bgdl\b|jalisco|remot',title+' '+description) and any(city in title+' '+description for city in ('buenos aires','madrid','monterrey','ciudad de mexico'))
        if re.search(r'no (?:hay|tenemos|existen) (?:vacantes|ofertas|empleos)|no (?:jobs|vacancies) (?:found|available)',description): meaningful=False
        if title.strip() and meaningful and url and related and not wrong_city and url not in seen:
            useful.append(item);seen.add(url)
    quantity=re.search(r'\b(\d+)\s+(?:ofertas|empleos|vacantes|resultados)\b',text)
    enough=bool(useful) and (not quantity or len(useful)>=int(quantity.group(1)))
    analysis=bool(re.search(r'analiz|compara|resumi|resume|resumen|analisis',text))
    return useful,enough,jobs,analysis
