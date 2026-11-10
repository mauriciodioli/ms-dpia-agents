"""Agent engine foundations. Importing this package starts no processes or I/O."""


def init_app(app):
    from .api import api, admin
    from . import integration_api  # Register routes before blueprint registration.
    app.register_blueprint(api)
    app.register_blueprint(admin)
    from .developer_portal import portal
    app.register_blueprint(portal)
    from .cli import dispatch_command, outbox_command, recover_command, worker_command, inbox_command
    app.cli.add_command(dispatch_command)
    app.cli.add_command(outbox_command)
    app.cli.add_command(recover_command)
    app.cli.add_command(worker_command)
    app.cli.add_command(inbox_command)
