"""Backend operation switches, independent of global provider availability."""
from sqlalchemy import select
from .errors import EngineError
from .integration_models import integrations

KEY = 'video-operation-policy'
DEFAULTS = {'custom_script': True, 'openai_script': False, 'heygen_produce': True}


def load(conn):
    row = conn.execute(select(integrations).where(integrations.c.id == KEY)).mappings().first()
    return {**DEFAULTS, **(row['config'] if row else {})}, row['revision'] if row else 0


def require(conn, operation):
    switches, _ = load(conn)
    if switches.get(operation) is not True:
        raise EngineError('VIDEO_OPERATION_DISABLED', 409)
