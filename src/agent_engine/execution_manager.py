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

    def _plan(self, agent, body, *, permitted_tools=None):
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
            return body
        return self._plan(agent, body)

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
