"""MCP persistence; global servers, explicit owner/agent/tool grants."""
from uuid import uuid4
from sqlalchemy import select, insert, update, and_
from sqlalchemy import inspect
from . import mcp_models as m
from . import models as engine
from .auth import now_utc
from .errors import EngineError


def tool_id(value):
    return 'mcp.' + value.replace('-', '')


class MCPRepository:
    def __init__(self, conn):
        self.conn = conn

    def server(self, server_id, principal=None, *, lock=False, deleted=False):
        q = select(m.servers).where(m.servers.c.id == server_id)
        if not deleted:q=q.where(m.servers.c.deleted_at.is_(None))
        if principal and not principal.admin:q=q.where(m.servers.c.created_by == str(principal.owner_id))
        row=self.conn.execute(q.with_for_update() if lock else q).mappings().first()
        if row is None:raise EngineError('mcp_server_not_found',404)
        return row

    def listing(self, principal, limit, after=None):
        q=select(m.servers).where(m.servers.c.deleted_at.is_(None))
        if not principal.admin:q=q.where(m.servers.c.created_by==str(principal.owner_id))
        if after:q=q.where(m.servers.c.id>after)
        return self.conn.execute(q.order_by(m.servers.c.id).limit(limit+1)).mappings().all()

    def tool(self, identifier, principal=None, *, lock=False):
        row=self.conn.execute(select(m.tools).where(m.tools.c.id==identifier).with_for_update() if lock else
                              select(m.tools).where(m.tools.c.id==identifier)).mappings().first()
        if row is None:raise EngineError('mcp_tool_not_found',404)
        self.server(row['server_id'],principal,lock=lock)
        return row

    def tools(self, server_id):
        return self.conn.execute(select(m.tools).where(m.tools.c.server_id==server_id).order_by(m.tools.c.tool_name)).mappings().all()

    def insert(self, table, values):
        self.conn.execute(insert(table).values(**values))

    def change_server(self, row, actor, **values):
        changed=self.conn.execute(update(m.servers).where(m.servers.c.id==row['id'],m.servers.c.revision==row['revision'])
            .values(revision=row['revision']+1,updated_by=actor,updated_at=now_utc(),**values)).rowcount
        if changed!=1:raise EngineError('revision_conflict',409)
        return self.server(row['id'],deleted=True)

    def change_tool(self, identifier, **values):
        self.conn.execute(update(m.tools).where(m.tools.c.id==identifier).values(updated_at=now_utc(),**values))

    def revoke_server(self, server_id):
        ids=select(m.tools.c.id).where(m.tools.c.server_id==server_id)
        self.conn.execute(update(m.grants).where(m.grants.c.tool_id.in_(ids)).values(enabled=False,updated_at=now_utc()))
        self.conn.execute(update(m.tools).where(m.tools.c.server_id==server_id).values(enabled=False,updated_at=now_utc()))

    def event(self, server_id, actor, action, *, tool=None, details=None, reason=None):
        self.insert(m.audit,dict(id=str(uuid4()),server_id=server_id,tool_id=tool,actor_id=actor,action=action,
                                details=details or {},reason_code=reason,created_at=now_utc()))

    def agent(self, owner, agent_id):
        return self.conn.execute(select(engine.agents).where(engine.agents.c.owner_id==owner,engine.agents.c.id==agent_id,
            ~select(engine.agent_deletions.c.agent_id).where(engine.agent_deletions.c.agent_id==agent_id).exists()).with_for_update()).mappings().first()

    def grant(self, owner, agent_id, tool, enabled, actor):
        q=and_(m.grants.c.owner_id==owner,m.grants.c.agent_id==agent_id,m.grants.c.tool_id==tool)
        existing=self.conn.execute(select(m.grants).where(q).with_for_update()).first()
        if existing:self.conn.execute(update(m.grants).where(q).values(enabled=enabled,granted_by=actor,updated_at=now_utc()))
        else:self.insert(m.grants,dict(owner_id=owner,agent_id=agent_id,tool_id=tool,enabled=enabled,granted_by=actor,created_at=now_utc(),updated_at=now_utc()))
        if enabled:
            cap=tool_id(tool)
            exists=self.conn.execute(select(engine.agent_capabilities.c.tool_id).where(engine.agent_capabilities.c.owner_id==owner,
                       engine.agent_capabilities.c.agent_id==agent_id,engine.agent_capabilities.c.tool_id==cap)).first()
            if not exists:self.insert(engine.agent_capabilities,dict(owner_id=owner,agent_id=agent_id,tool_id=cap))

    def catalog(self, owner=None):
        if not inspect(self.conn).has_table('ae_mcp_servers'):return []
        q=select(m.tools,m.servers.c.revision.label('server_revision'),m.servers.c.priority).join(m.servers).where(
            m.servers.c.deleted_at.is_(None),m.servers.c.enabled.is_(True),m.tools.c.enabled.is_(True))
        if owner is not None:q=q.where(select(m.grants.c.tool_id).where(m.grants.c.owner_id==owner,
            m.grants.c.tool_id==m.tools.c.id,m.grants.c.enabled.is_(True)).exists())
        return self.conn.execute(q.order_by(m.servers.c.priority,m.tools.c.tool_name)).mappings().all()

    def authorized(self, owner, agent_id, tool_uuid):
        server_id=self.conn.execute(select(m.tools.c.server_id).where(m.tools.c.id==tool_uuid)).scalar_one_or_none()
        if not server_id:raise EngineError('mcp_tool_revoked',403)
        server=self.server(server_id,lock=True)
        tool=self.tool(tool_uuid,lock=True)
        grant=self.conn.execute(select(m.grants).where(m.grants.c.owner_id==owner,m.grants.c.agent_id==agent_id,
            m.grants.c.tool_id==tool_uuid,m.grants.c.enabled.is_(True)).with_for_update()).mappings().first()
        if not server['enabled'] or not tool['enabled'] or not grant:raise EngineError('mcp_tool_revoked',403)
        return server,tool

    def execution(self, identifier, **values):
        self.conn.execute(update(m.executions).where(m.executions.c.id==identifier).values(**values))

    def revoke_tool(self, identifier):
        self.conn.execute(update(m.grants).where(m.grants.c.tool_id==identifier).values(enabled=False,updated_at=now_utc()))
