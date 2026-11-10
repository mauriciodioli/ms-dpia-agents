"""Generic cooperative worker runtime; provider-specific agents belong to Phase D."""
from dataclasses import dataclass
from threading import Event, Thread
from uuid import uuid4
from jsonschema import Draft202012Validator
from .errors import EngineError
from .streams import TaskMessage


@dataclass(frozen=True)
class Handler:
    run: object
    output_schema: dict
    requires_provider_grant: bool = True


class HandlerRegistry:
    def __init__(self):
        self.handlers = {}

    def register(self, tool_id, handler):
        if tool_id in self.handlers or not callable(handler.run):
            raise EngineError('invalid_handler')
        Draft202012Validator.check_schema(handler.output_schema)
        self.handlers[tool_id] = handler


class ExecutionContext:
    def __init__(self, box, lease):
        self.box, self.lease = box, lease
        self.cancelled = Event()

    @property
    def previous_outputs(self):
        return self.lease.previous_outputs

    def heartbeat(self):
        if self.cancelled.is_set():
            raise EngineError('lease_lost', 409)
        self.box.heartbeat(self.lease)

    def mark_submitting(self, expected_integration_revision=None):
        self.heartbeat()
        self.box.mark_submitting(self.lease, expected_integration_revision)

    def mark_submitted(self, provider_job_id):
        self.box.mark_submitted(self.lease, provider_job_id)


class Worker:
    def __init__(self, box, streams, handlers, capabilities, *, worker_id=None, auto_heartbeat=True):
        self.box, self.streams, self.handlers = box, streams, handlers
        self.capabilities = tuple(capabilities)
        self.worker_id = worker_id or str(uuid4())
        self.auto_heartbeat = auto_heartbeat
        self.registered = False

    def start(self):
        if self.registered:
            return
        supported = {self.box.registry.tools[name].capability for name in self.handlers.handlers
                     if name in self.box.registry.tools}
        if not self.capabilities or not set(self.capabilities).issubset(supported):
            raise EngineError('worker_handlers_not_configured', 503)
        for capability in self.capabilities:
            self.streams.ensure_group(capability)
        self.box.register_worker(self.worker_id, self.capabilities)
        self.registered = True

    def _renew_loop(self, context, stop):
        while not stop.wait(max(1, self.box.policy.lease_seconds//3)):
            try:
                context.heartbeat()
            except Exception:
                context.cancelled.set()
                return  # No exception text: drivers/providers can embed secrets.

    def _handle(self, capability, message_id, fields):
        try:
            message = TaskMessage.parse(fields)
        except EngineError:
            self.streams.ack(capability, message_id)
            return 'INVALID'
        # Handler policy is trusted local configuration, never a Redis field.
        tool_id = None
        from sqlalchemy import select
        from .models import tasks
        with self.box.engine.connect() as conn:
            tool_id = conn.execute(select(tasks.c.tool_id).where(tasks.c.owner_id == message.owner_id,
                tasks.c.id == message.task_id, tasks.c.job_id == message.job_id)).scalar_one_or_none()
        handler = self.handlers.handlers.get(tool_id)
        if tool_id is None:
            self.streams.ack(capability, message_id)
            return 'INVALID'
        if handler is None:
            return 'DEFER'
        decision, lease = self.box.claim(self.worker_id, capability, message,
                                        require_provider=handler.requires_provider_grant)
        if decision == 'ACK':
            self.streams.ack(capability, message_id)
            return 'SKIPPED'
        if decision != 'LEASE':
            return 'DEFER'
        context, stop = ExecutionContext(self.box, lease), Event()
        ticker = Thread(target=self._renew_loop, args=(context, stop), daemon=True, name='agent-lease-heartbeat')
        if self.auto_heartbeat:
            ticker.start()
        try:
            output = handler.run(context, lease.parameters)
            if not Draft202012Validator(handler.output_schema).is_valid(output):
                raise EngineError('invalid_task_output')
            context.heartbeat()  # Fenced even if a handler returned after its deadline.
            self.box.complete(lease, output, require_provider=handler.requires_provider_grant)
        except Exception as error:
            if isinstance(error, EngineError) and error.code in ('integration_disabled', 'revision_conflict'):
                try:
                    self.box.defer_integration(lease)
                    return 'DEFER'
                except EngineError as deferred:
                    if deferred.code == 'lease_lost':
                        return 'LEASE_LOST'
                    # A submitted task must retain the existing uncertain policy.
                    if deferred.code != 'provider_already_submitted':
                        raise
            try:
                self.box.failed(lease)  # Safe retries only before external submission.
            except EngineError as error:
                if error.code == 'lease_lost':
                    return 'LEASE_LOST'  # Leave PEL entry for reconciliation.
                raise
            self.streams.ack(capability, message_id)  # Retry intent is now durable in MySQL.
            return 'RETRY_OR_BLOCKED'
        finally:
            stop.set()
            if self.auto_heartbeat:
                ticker.join(timeout=4)
        # A lost ACK may redeliver, but COMPLETED tasks cannot be claimed again.
        self.streams.ack(capability, message_id)
        return 'COMPLETED'

    def work_once(self):
        self.start()
        self.box.recover()
        self.box.idle(self.worker_id)
        outcomes = []
        for capability in self.capabilities:
            self.streams.ensure_group(capability)  # Heal group loss after Redis restart/reset.
            pending = self.streams.reclaim(capability, self.worker_id,
                idle_ms=self.box.policy.lease_seconds*1000, count=10)
            for message_id, fields in pending:
                outcomes.append(self._handle(capability, message_id, fields))
            for message_id, fields in self.streams.read(capability, self.worker_id, count=1):
                outcomes.append(self._handle(capability, message_id, fields))
        return outcomes
