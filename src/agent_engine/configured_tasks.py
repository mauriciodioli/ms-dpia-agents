"""Configuration of user tasks; never dispatches work or changes agent defaults."""
from dataclasses import replace
from .auth import now_utc
from .contracts import AGENT_UPDATE, validate
from .configured_task_repository import ConfiguredTaskRepository
from .errors import EngineError
from .management import locked_agent, audit_agent
from .tools import default_registry
from .task_schedules import schedules_for_task, save_task_schedule

CONFIG_KEY = '_agent_configuration'
REVISION_KEY = '_configuration_revision'


def scoped_agent(conn, principal, agent_id, administrative=False):
    if administrative:
        if principal.kind != 'SESSION' or not principal.admin:
            raise EngineError('administrator_session_required', 403)
        owner = ConfiguredTaskRepository(conn).owner(agent_id)
        if owner is None:
            raise EngineError('agent_not_found', 404)
        principal = replace(principal, owner_id=owner, all_agents=True, agent_ids=frozenset())
    ConfiguredTaskRepository(conn).lock_owner(principal.owner_id)
    return principal, locked_agent(conn, principal, agent_id)


def public_task(row, agent_id):
    params = row['parametros'] or {}
    return dict(id=row['id'], agent_id=agent_id, name=row['nombre'] or row['tipo'], type=row['tipo'],
                enabled=bool(row['habilitada']), revision=params.get(REVISION_KEY, 1),
                configured=CONFIG_KEY in params)


class ConfiguredTaskManager:
    def __init__(self, conn, principal, registry=None):
        self.conn, self.principal = conn, principal
        self.repository = ConfiguredTaskRepository(conn)
        self.registry = registry or default_registry(conn=conn,owner=principal.owner_id)

    def access(self, agent_id, administrative=False):
        return scoped_agent(self.conn, self.principal, agent_id, administrative)

    def listing(self, agent_id):
        principal, agent = self.access(agent_id)
        return [{**public_task(row, agent_id), 'schedules':schedules_for_task(self.conn,agent,row['id'])} for row in self.repository.rows(agent)
                if not (row['parametros'] or {}).get('_deleted_at')]

    def detail(self, agent_id, task_id, *, administrative=False, body=None):
        principal, agent = self.access(agent_id, administrative)
        rows = self.repository.rows(agent, task_id)
        if not rows or (rows[0]['parametros'] or {}).get('_deleted_at'):
            raise EngineError('task_not_found', 404)
        row = rows[0]
        params = dict(row['parametros'] or {})
        if body is not None:
            self.principal.require('agents:write')
            schedule = body.get('schedule')
            if 'schedule' in body and not isinstance(schedule,dict):raise EngineError('invalid_contract')
            body = {key:value for key,value in body.items() if key != 'schedule'}
            validate(AGENT_UPDATE, body)
            self.registry.validate_agent({key:value for key,value in body.items() if key != 'expected_revision'})
            if body['expected_revision'] != params.get(REVISION_KEY, 1):
                raise EngineError('revision_conflict', 409)
            configuration = {key:value for key,value in body.items() if key != 'expected_revision'}
            from .execution_manager import automatic_request
            candidate={'limits':configuration['limits'],'pipeline':[{'tool':tool,'parameters':{}} for tool in configuration['capabilities']]}
            configuration={**configuration,'limits':automatic_request(agent,candidate)['limits']}
            from .dispatcher import validate_request_budget
            validate_request_budget(agent, {'limits':configuration['limits']})
            params[CONFIG_KEY] = configuration
            params[REVISION_KEY] = body['expected_revision'] + 1
            self.repository.save(row, name=body['name'].strip(), parameters=params, now=now_utc())
            audit_agent(self.conn, self.principal, agent, 'TASK_CONFIGURATION_UPDATED',
                        {'task_id':task_id, 'task_revision':params[REVISION_KEY]})
            row = {**row, 'nombre':body['name'].strip(), 'parametros':params}
            if schedule is None:
                # Keep managed schedules' execution snapshots in sync with this task's tools/instructions.
                from .contracts import SCHEDULE_CREATE
                existing = self.repository.task_schedules(agent,task_id)
                if len(existing)==1 and existing[0]['definition'].get('configured_task_schedule'):
                    current=existing[0]
                    schedule={key:value for key,value in current['definition'].items() if key in SCHEDULE_CREATE['properties']}
                    schedule.update(enabled=current['enabled'],expected_revision=current['revision'])
            if schedule is not None:
                save_task_schedule(self.conn,principal,agent,row,schedule)
        task = public_task(row, agent_id)
        task['schedules'] = schedules_for_task(self.conn,agent,task_id)
        task['configuration'] = params.get(CONFIG_KEY) or dict(name=task['name'], description='',
            instructions=agent['instructions'], timezone=agent['timezone'], capabilities=self.repository.capabilities(agent),
            limits=agent['limits'], tool_parameters=agent['search_parameters'])
        return task

    def update_schedule(self, agent_id, task_id, command, *, administrative=False):
        self.principal.require('agents:write')
        principal, agent = self.access(agent_id, administrative)
        rows = self.repository.rows(agent, task_id)
        if not rows or (rows[0]['parametros'] or {}).get('_deleted_at'):
            raise EngineError('task_not_found',404)
        save_task_schedule(self.conn,principal,agent,rows[0],command)
        return {'id':task_id,'schedules':schedules_for_task(self.conn,agent,task_id)}

    def preview_schedule(self, agent_id, task_id, command, *, administrative=False):
        from datetime import timezone
        from zoneinfo import ZoneInfo
        from .contracts import TASK_SCHEDULE_UPDATE, iso
        from .scheduling import next_occurrence, delivery_time
        principal, agent = self.access(agent_id, administrative)
        rows = self.repository.rows(agent, task_id)
        if not rows or (rows[0]['parametros'] or {}).get('_deleted_at'):
            raise EngineError('task_not_found',404)
        validate(TASK_SCHEDULE_UPDATE,command)
        due = next_occurrence(command,now_utc())
        if command['enabled'] and due is None:raise EngineError('execution_time_in_past',422)
        if due is not None:delivery_time(command,due)
        local=due.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(command['timezone'])).isoformat() if due else None
        return {'next_run_at':iso(due) if command['enabled'] else None, 'timezone':command['timezone'],
                'local_next_run_at':local if command['enabled'] else None,
                'candidate_run_at':iso(due), 'local_candidate_run_at':local}

    def administration(self, limit=25, after=0):
        if self.principal.kind != 'SESSION' or not self.principal.admin:
            raise EngineError('administrator_session_required', 403)
        items = []
        for row in self.repository.administration(limit, after):
            if (row['parametros'] or {}).get('_deleted_at'):
                continue
            if row.get('ae_agent_id') not in (None, row['engine_id']):
                raise EngineError('task_agent_mismatch', 409)
            items.append({**public_task(row, row['engine_id']), 'agent_name':row['agent_name'], 'owner_id':row['owner_id']})
            if len(items) > limit:
                break
        return dict(items=items[:limit], next_cursor=items[limit-1]['id'] if len(items)>limit else None)
