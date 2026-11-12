"""Existing configured user tasks, distinct from ae_tasks worker steps. No DDL."""
from sqlalchemy import MetaData, Table, select, update, or_, inspect
from . import models as m
from .errors import EngineError


class ConfiguredTaskRepository:
    def __init__(self, conn):
        self.conn = conn

    def table(self):
        if not hasattr(self, '_tasks'):
            self._tasks = Table('agente_tareas', MetaData(), autoload_with=self.conn, resolve_fks=False)
        return self._tasks

    def rows(self, agent, task_id=None):
        if not inspect(self.conn).has_table('agente_tareas'):
            return []
        t = self.table()
        # A legacy task may not yet have its nullable engine link populated.
        relation = t.c.agente_id == agent['legacy_agent_id'] if agent['legacy_agent_id'] is not None else t.c.id.is_(None)
        if 'ae_agent_id' in t.c:
            relation = or_(relation, t.c.ae_agent_id == agent['id'])
        query = select(t).where(relation).order_by(t.c.id)
        if task_id is not None:
            query = query.where(t.c.id == task_id)
        rows = self.conn.execute(query.with_for_update()).mappings().all()
        for row in rows:
            if (agent['legacy_agent_id'] is None or row['agente_id'] != agent['legacy_agent_id']
                    or row.get('ae_agent_id') not in (None, agent['id'])):
                raise EngineError('task_agent_mismatch', 409)
        return rows

    def save(self, row, *, name, parameters, now):
        t = self.table()
        self.conn.execute(update(t).where(t.c.id == row['id'], t.c.agente_id == row['agente_id'])
                          .values(nombre=name, parametros=parameters, actualizado_en=now))

    def administration(self, limit, after=0):
        if not inspect(self.conn).has_table('agente_tareas'):
            return []
        t = self.table()
        query = select(t, m.agents.c.id.label('engine_id'), m.agents.c.name.label('agent_name'),
                       m.agents.c.owner_id).join(m.agents, m.agents.c.legacy_agent_id == t.c.agente_id).where(
            t.c.id > after, t.c.parametros['_deleted_at'].as_string().is_(None),
            ~select(m.agent_deletions.c.agent_id).where(m.agent_deletions.c.agent_id == m.agents.c.id).exists())
        # Filtering tombstones happens before pagination so empty pages cannot hide later tasks.
        return self.conn.execute(query.order_by(t.c.id).limit(limit + 1)).mappings()

    def owner(self, agent_id):
        return self.conn.execute(select(m.agents.c.owner_id).where(m.agents.c.id == agent_id)).scalar_one_or_none()

    def capabilities(self, agent):
        return list(self.conn.execute(select(m.agent_capabilities.c.tool_id).where(
            m.agent_capabilities.c.owner_id == agent['owner_id'], m.agent_capabilities.c.agent_id == agent['id'])
            .order_by(m.agent_capabilities.c.tool_id)).scalars())

    def lock_owner(self, owner):
        from model.usuario import Usuario
        self.conn.execute(select(Usuario.id).where(Usuario.id == owner).with_for_update()).first()

    def task_schedules(self, agent, task_id):
        return self.conn.execute(select(m.schedules).where(m.schedules.c.owner_id==agent['owner_id'],
            m.schedules.c.agent_id==agent['id'],m.schedules.c.legacy_task_id==task_id).with_for_update()).mappings().all()

    def original_schedule(self, agent):
        if not inspect(self.conn).has_table('agente_programaciones'):
            return None
        table=Table('agente_programaciones',MetaData(),autoload_with=self.conn,resolve_fks=False)
        return self.conn.execute(select(table).where(table.c.agente_id==agent['legacy_agent_id'])).mappings().first()

    def bind_task(self, task, agent, parameters):
        table=self.table()
        values={'parametros':parameters}
        if 'ae_agent_id' in table.c:values['ae_agent_id']=agent['id']
        self.conn.execute(update(table).where(table.c.id==task['id'],table.c.agente_id==agent['legacy_agent_id']).values(**values))

    def persist_schedule(self, values, previous=None):
        from sqlalchemy import insert
        if previous:
            self.conn.execute(update(m.schedules).where(m.schedules.c.id==previous['id'],
                m.schedules.c.owner_id==previous['owner_id'],m.schedules.c.revision==previous['revision']).values(**values))
        else:self.conn.execute(insert(m.schedules).values(**values))

    def retire_general_pwa_schedule(self, agent):
        from uuid import uuid5, NAMESPACE_URL
        identifier=str(uuid5(NAMESPACE_URL,'pwa-schedule:'+agent['id']))
        self.conn.execute(update(m.schedules).where(m.schedules.c.id==identifier,
            m.schedules.c.owner_id==agent['owner_id'],m.schedules.c.agent_id==agent['id'],
            m.schedules.c.legacy_task_id.is_(None),
            (m.schedules.c.enabled.is_(True) | m.schedules.c.next_run_at.is_not(None)))
            .values(enabled=False,next_run_at=None,revision=m.schedules.c.revision+1))
