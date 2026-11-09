"""Explicit Dispatcher process. Nothing runs during web application startup."""
import time
import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy.exc import SQLAlchemyError
from .api import engine
from .dispatcher import Dispatcher
from .errors import EngineError


@click.command('agent-dispatch')
@click.option('--batch-size', type=click.IntRange(1, 1000), default=100, show_default=True)
@click.option('--watch', is_flag=True, help='Repeat ticks until interrupted; otherwise run one tick.')
@click.option('--interval', type=click.IntRange(1, 60), default=5, show_default=True)
@with_appcontext
def dispatch_command(batch_size, watch, interval):
    """Advance due jobs and schedules using MySQL only. Does not apply migrations."""
    while True:
        try:
            with engine().begin() as conn:
                report = Dispatcher(conn).tick(batch_size)
        except SQLAlchemyError:
            raise click.ClickException('engine_storage_unavailable') from None
        except EngineError as error:
            raise click.ClickException(error.code) from None
        click.echo(' '.join(f'{name}={len(rows)}' for name, rows in report.items()))
        if not watch:
            return
        time.sleep(interval)


def _repeat_queue_operation(callback, watch, interval):
    while True:
        try:
            result = callback()
        except SQLAlchemyError:
            raise click.ClickException('engine_storage_unavailable') from None
        except EngineError as error:
            raise click.ClickException(error.code) from None
        click.echo(str(result))  # Counts/fixed outcome codes only, never task data.
        if not watch:
            return
        time.sleep(interval)


@click.command('agent-outbox')
@click.option('--watch', is_flag=True)
@click.option('--interval', type=click.IntRange(1, 60), default=5)
@click.option('--batch-size', type=click.IntRange(1, 1000), default=100)
@with_appcontext
def outbox_command(watch, interval, batch_size):
    """Explicitly publish committed MySQL work to Redis Streams; never runs DDL."""
    from .task_box import TaskBox
    from .streams import RedisStreams
    from .outbox import OutboxPublisher
    box = TaskBox(engine())
    try:
        streams = RedisStreams.from_config(current_app.config)
    except EngineError as error:
        raise click.ClickException(error.code) from None
    publisher = OutboxPublisher(box, streams)
    def cycle():
        box.recover(batch_size)
        return publisher.publish_batch(batch_size)
    _repeat_queue_operation(cycle, watch, interval)


@click.command('agent-recover')
@click.option('--batch-size', type=click.IntRange(1, 1000), default=100)
@with_appcontext
def recover_command(batch_size):
    """One explicit MySQL reconciliation pass. No Redis or provider calls."""
    from .task_box import TaskBox
    _repeat_queue_operation(lambda: TaskBox(engine()).recover(batch_size), False, 1)


@click.command('agent-worker')
@click.option('--local-test', is_flag=True, help='Explicitly enable the no-provider demo handler.')
@click.option('--capability', multiple=True, required=True)
@click.option('--watch', is_flag=True)
@click.option('--interval', type=click.IntRange(1, 60), default=5)
@with_appcontext
def worker_command(capability, watch, interval, local_test):
    """Generic runner. Requires explicitly installed trusted Phase D handlers."""
    from .worker import Worker, HandlerRegistry
    from .task_box import TaskBox
    from .streams import RedisStreams
    handlers = current_app.extensions.get('agent_engine_handlers')
    if local_test:
        if set(capability) != {'local-test'}:
            raise click.ClickException('local_test_requires_local_test_capability_only')
        from .demo_handler import demo_handlers
        handlers = demo_handlers()
    if not isinstance(handlers, HandlerRegistry) or not handlers.handlers:
        raise click.ClickException('worker_handlers_not_configured')
    try:
        worker = Worker(TaskBox(engine()), RedisStreams.from_config(current_app.config), handlers, capability)
    except EngineError as error:
        raise click.ClickException(error.code) from None
    _repeat_queue_operation(worker.work_once, watch, interval)
