"""Centrally managed access to the shared HeyGen connection."""
from sqlalchemy import select
from .integration_models import integrations
from .rest_providers.models import providers
from .errors import EngineError

KEY='shared-video-provider'


def resolve_shared(conn, owner):
    policy=conn.execute(select(integrations).where(integrations.c.id==KEY)).mappings().first()
    config=policy['config'] if policy and policy['enabled'] else {}
    if not isinstance(config,dict):
        raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
    if config.get('access')!='all_active_users':
        raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
    from .auth import active_user
    active_user(conn,owner)
    row=conn.execute(select(providers).where(providers.c.id==config.get('provider_id'),
        providers.c.owner_id==config.get('provider_owner_id'),providers.c.adapter=='heygen',
        providers.c.enabled.is_(True))).mappings().first()
    if not row:raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
    return dict(row)


def resolve(conn, owner):
    own=conn.execute(select(providers).where(providers.c.owner_id==owner,
        providers.c.adapter=='heygen',providers.c.enabled.is_(True))).mappings().all()
    if len(own)>1:raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
    if own:return dict(own[0])
    return resolve_shared(conn,owner)
