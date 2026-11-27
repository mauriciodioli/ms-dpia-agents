"""Agent engine foundations. Importing this package starts no processes or I/O."""


def init_app(app):
    from .api import api, admin
    from . import result_review_api
    from . import workspace_assessment
    from . import pwa_history
    from . import pwa_activation
    from . import pause_control
    from . import deletion_api
    from . import configured_task_api
    from . import mcp_api
    from .rest_providers import api as rest_provider_api
    from .mcp_oauth import api as mcp_oauth_api
    from . import video_cost_api
    from . import integration_api  # Register routes before blueprint registration.
    app.register_blueprint(api)
    app.register_blueprint(admin)
    from .developer_portal import portal
    app.register_blueprint(portal)
    from .cli import dispatch_command, outbox_command, recover_command, worker_command, inbox_command, video_check_command, video_reconcile_command, video_recover_command
    from .cli import economic_diagnose_command
    app.cli.add_command(economic_diagnose_command)
    app.cli.add_command(dispatch_command)
    app.cli.add_command(outbox_command)
    app.cli.add_command(recover_command)
    app.cli.add_command(worker_command)
    app.cli.add_command(inbox_command)
    app.cli.add_command(video_check_command)
    app.cli.add_command(video_reconcile_command)
    app.cli.add_command(video_recover_command)
