"""Manager-facing orchestration entry point; Dispatcher remains responsible for persistence."""
from flask import current_app
from .planner import Planner
from .integrations import IntegrationService


class ExecutionManager:
    def __init__(self, conn, registry):
        self.conn, self.registry = conn, registry
        self.planner_usage = None

    def prepare(self, agent, body, job_id=None):
        if 'pipeline' in body:
            return body
        service = IntegrationService(current_app.extensions.get('agent_engine_engine') or __import__('utils.db', fromlist=['db']).db.engine, current_app.config)
        planner = Planner(self.conn, service=service, registry=self.registry)
        steps = planner.plan(body['objective'], agent, body['limits'])
        self.planner_usage = planner.usage_record
        return {**body, 'pipeline':steps, 'instructions':body.get('instructions',body['objective'])}
