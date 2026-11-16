"""Prepare execution plans and resources; workers only execute validated steps."""
from flask import current_app
from .planner import Planner
from .integrations import IntegrationService
from .errors import EngineError


def automatic_request(agent, body):
    """Derive the technical call allowance, without increasing the service ceiling.

    Candidate steps may exceed that ceiling: the manager will optimize them at
    dispatch, after connectivity checks. Other caller limits are never increased.
    """
    limits = dict(body['limits'])
    ceiling = agent['limits']['max_tool_calls']
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
        import re
        try:
            validate(RESULT, output)
        except EngineError:
            # Existing local/custom outputs retain their final review contract.
            if output.get('schema_version') == 'agents.result.v1':
                return 'REJECT', 'INVALID_RESULT_CONTRACT'
            return ('CONTINUE', 'NEXT_AUTHORIZED_STAGE_REQUIRED') if following else ('ACCEPT', 'PLAN_COMPLETED')
        # Only structured job offers can short-circuit optional analysis. Free text
        # cannot establish role/location sufficiency deterministically.
        objective = job['request_snapshot'].get('objective') or job['request_snapshot'].get('instructions', '')
        text = objective.casefold()
        items = output.get('items') or []
        stop = {'buscar','buscá','busca','empleos','empleo','trabajo','ofertas','laborales',
                'oportunidades','de','en','para','y','el','la','los','las','méxico','mexico'}
        terms = [x for x in re.findall(r'[\w]+', text) if x not in stop and len(x)>2]
        jobs = any(word in text for word in ('empleo', 'trabajo', 'laboral'))
        explicit_analysis = any(word in text for word in ('analiz', 'compar', 'resum', 'anális'))
        requested_count = re.search(r'\b(\d+)\s+(?:ofertas|empleos|vacantes|resultados)\b', text)
        enough = not requested_count or len(items) >= int(requested_count.group(1))
        sufficient = (jobs and enough and terms and items and all(item.get('company') and item.get('location')
            and item.get('url','').startswith(('https://','http://')) for item in items)
            and all(term in ' '.join(str(item.get(k,'')) for item in items
                for k in ('title','description','location')).casefold() for term in terms))
        optional = following and all(step['tool_id']=='openai.analysis' for step in following)
        if task['tool_id'].startswith('mcp.') and sufficient and optional and not explicit_analysis:
            return 'ACCEPT', 'STRUCTURED_JOB_OBJECTIVE_SATISFIED'
        return ('CONTINUE', 'NEXT_AUTHORIZED_STAGE_REQUIRED') if following else ('ACCEPT', 'PLAN_COMPLETED')

    def advance(self, box, conn, job, task, output):
        """Persist decision and authorize one next step under the existing job lock."""
        from sqlalchemy import select, update, func
        from . import models as m
        following = conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
            m.tasks.c.job_id==job['id'],m.tasks.c.position>task['position'])
            .order_by(m.tasks.c.position).with_for_update()).mappings().all()
        decision, reason = self.evaluate_step(job, task, output, following)
        snapshot = dict(job['configuration_snapshot'])
        decisions = dict(snapshot.get('manager_decisions', {}))
        decisions[task['id']] = {'decision':decision,'reason':reason,'tool':task['tool_id']}
        snapshot['manager_decisions'] = decisions
        conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id'])
            .values(configuration_snapshot=snapshot))
        if decision == 'REJECT':
            box._fail(conn, job, reason)
            return
        if decision == 'CONTINUE':
            limits = job['request_snapshot']['limits']
            used = conn.execute(select(func.sum(m.tasks.c.attempt_count)).where(
                m.tasks.c.owner_id==job['owner_id'],m.tasks.c.job_id==job['id'])).scalar() or 0
            if used >= limits['max_tool_calls']:
                box._fail(conn,job,'TASK_ATTEMPT_BUDGET_EXCEEDED')
                return
            next_task = following[0]
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
                m.tasks.c.id==next_task['id']).values(state='PENDING'))
            box._rearm(conn,job,next_task,box.now())
            box._event(conn,job,'MANAGER_CONTINUE',progress=int(100*(task['position']+1)/(task['position']+1+len(following))))
            return
        if following:
            conn.execute(update(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],
                m.tasks.c.job_id==job['id'],m.tasks.c.position>task['position'])
                .values(state='CANCELLED'))
        from .dispatcher import Dispatcher
        Dispatcher(conn, now=box.now(), registry=self.registry).complete_result(job,output)

    def handle_failure(self, box, conn, job, task, error_code):
        # Keep the established safe-retry/uncertain-submission policy intact.
        from sqlalchemy import update
        from . import models as m
        snapshot = dict(job['configuration_snapshot'])
        history = list(snapshot.get('manager_failures', []))
        history.append({'task_id':task['id'],'attempt':task['attempt_count'],
                        'reason':error_code or 'HANDLER_FAILED',
                        'decision':'REJECT' if task['attempt_count'] >= box.policy.max_attempts else
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
        if permitted_tools is not None:
            planner.permitted_tools = frozenset(permitted_tools)
            planner.task_instructions = body.get('instructions', '')
        objective = body.get('objective') or 'Prepare the smallest executable plan for the complete task instructions supplied below.'
        steps = planner.plan(objective, agent, body['limits'])
        self.planner_usage = planner.usage_record
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
            for provider,spec in PROVIDERS.items():
                if spec['tool'] in selected:ensure_access(self.conn,agent,provider)
            return body
        result=self._plan(agent, body)
        from .integrations import PROVIDERS
        from .provider_access import ensure_access
        for provider,spec in PROVIDERS.items():
            if any(step['tool']==spec['tool'] for step in result['pipeline']):ensure_access(self.conn,agent,provider)
        return result

    def finalize(self, agent, body, *, scheduled=False, automatic=False):
        """Called after authorization/schema checks, before any job reaches a worker."""
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
