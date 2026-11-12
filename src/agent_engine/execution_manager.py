"""Manager-facing orchestration entry point; Dispatcher remains responsible for persistence."""
from flask import current_app
from .planner import Planner
from .integrations import IntegrationService


class ExecutionManager:
    def __init__(self, conn, registry):
        self.conn, self.registry = conn, registry

    def prepare(self, agent, body, job_id=None):
        if 'pipeline' in body:
            return body
        service = IntegrationService(current_app.extensions.get('agent_engine_engine') or __import__('utils.db', fromlist=['db']).db.engine, current_app.config)
        steps = Planner(self.conn, service=service, registry=self.registry).plan(
            body['objective'], agent, body['limits'], job_id=job_id)
        return {**body, 'pipeline':steps, 'instructions':body.get('instructions',body['objective'])}
