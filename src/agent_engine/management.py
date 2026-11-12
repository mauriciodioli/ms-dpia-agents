"""Tenant-scoped agent configuration, locking and revisioned audit."""
from uuid import uuid4
from sqlalchemy import select, insert, update, delete
from . import models as m
from .auth import now_utc
from .contracts import AGENT_CREATE, AGENT_UPDATE, REVISION, validate
from .errors import EngineError
from .repository import ReadRepository, agent_access
from .tools import default_registry


def locked_agent(conn, principal, agent_id):
    row = conn.execute(select(m.agents).where(m.agents.c.owner_id == principal.owner_id,
        m.agents.c.id == agent_id, agent_access(principal),
        ~select(m.agent_deletions.c.agent_id).where(m.agent_deletions.c.agent_id==m.agents.c.id).exists()).with_for_update()).mappings().first()
    if row is None:
        raise EngineError('agent_not_found', 404)
    return row


def audit_agent(conn, principal, row, action, details, now=None):
    conn.execute(insert(m.agent_events).values(id=str(uuid4()), owner_id=row['owner_id'],
        agent_id=row['id'], revision=row['revision'], action=action, actor_type=principal.kind,
        actor_id=principal.actor_id, details=details, created_at=now or now_utc()))


class AgentManager:
    def __init__(self, conn, principal, registry=None):
        self.conn, self.principal = conn, principal
        self.registry = registry or default_registry()

    def save(self, body, agent_id=None):
        self.principal.require('agents:write')
        validate(AGENT_UPDATE if agent_id else AGENT_CREATE, body)
        definition = {key: value for key, value in body.items() if key != 'expected_revision'}
        self.registry.validate_agent(definition)
        now = now_utc()
        if agent_id:
            previous = locked_agent(self.conn, self.principal, agent_id)
            if previous['legacy_agent_id'] is not None:
                from .owner_identity import owner_email
                body={**body,'name':owner_email(self.conn,self.principal.owner_id)}
                definition['name']=body['name']
            if previous['revision'] != body['expected_revision']:
                raise EngineError('revision_conflict', 409)
        else:
            if not self.principal.all_agents:
                raise EngineError('all_agents_access_required', 403)
            agent_id, previous = str(uuid4()), None
        values = dict(name=body['name'].strip(), description=body.get('description', ''),
            instructions=body['instructions'], timezone=body['timezone'], limits=body['limits'],
            search_parameters=body.get('tool_parameters', {}), updated_at=now,
            revision=previous['revision']+1 if previous else 1)
        if previous:
            changed = self.conn.execute(update(m.agents).where(m.agents.c.id == agent_id,
                m.agents.c.owner_id == self.principal.owner_id,
                m.agents.c.revision == previous['revision']).values(**values)).rowcount
            if changed != 1:
                raise EngineError('revision_conflict', 409)
        else:
            self.conn.execute(insert(m.agents).values(id=agent_id, owner_id=self.principal.owner_id,
                configuration_state='DISABLED', created_at=now, **values))
        self.conn.execute(delete(m.agent_capabilities).where(m.agent_capabilities.c.owner_id == self.principal.owner_id,
            m.agent_capabilities.c.agent_id == agent_id))
        for tool_id in sorted(body['capabilities']):
            self.conn.execute(insert(m.agent_capabilities).values(owner_id=self.principal.owner_id,
                agent_id=agent_id, tool_id=tool_id))
        row = locked_agent(self.conn, self.principal, agent_id)
        audit_agent(self.conn, self.principal, row, 'AGENT_UPDATED' if previous else 'AGENT_CREATED', definition)
        return ReadRepository(self.conn, self.principal).public_agent(row, configuration=True)

    def save_identity(self, body, agent_id):
        self.principal.require('agents:write')
        if not isinstance(body, dict) or set(body) != {'name','description','instructions','timezone','expected_revision'}:
            raise EngineError('invalid_contract')
        row = locked_agent(self.conn, self.principal, agent_id)
        # Reuse the existing validator and persistence/audit path while keeping defaults intact.
        capabilities = ReadRepository(self.conn, self.principal).public_agent(row, configuration=True)['capabilities']
        return self.save({**body, 'capabilities':capabilities, 'limits':row['limits'],
                          'tool_parameters':row['search_parameters']}, agent_id)

    def set_enabled(self, agent_id, body, enabled):
        self.principal.require('agents:write')
        validate(REVISION, body)
        row = locked_agent(self.conn, self.principal, agent_id)
        from .owner_identity import persist_linked_name
        row=persist_linked_name(self.conn,row)
        if row['revision'] != body['expected_revision']:
            raise EngineError('revision_conflict', 409)
        state = 'ENABLED' if enabled else 'DISABLED'
        if row['configuration_state'] != state:
            changed = self.conn.execute(update(m.agents).where(m.agents.c.owner_id == self.principal.owner_id,
                m.agents.c.id == agent_id, m.agents.c.revision == row['revision']).values(
                    configuration_state=state, revision=row['revision']+1, updated_at=now_utc())).rowcount
            if changed != 1:
                raise EngineError('revision_conflict', 409)
            row = locked_agent(self.conn, self.principal, agent_id)
            audit_agent(self.conn, self.principal, row, 'AGENT_'+state, {})
        return ReadRepository(self.conn, self.principal).public_agent(row, configuration=True)

    def delete_agent(self,agent_id,body,**options):
        from .agent_deletion import delete_agent
        return delete_agent(self.conn,self.principal,agent_id,body,**options)
