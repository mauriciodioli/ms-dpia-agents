"""Connect existing B2B task schedules to the existing Dispatcher; never submit jobs."""
from uuid import uuid5, NAMESPACE_URL
from .auth import now_utc
from .contracts import SCHEDULE_CREATE, REQUEST_CREATE, validate
from .configured_task_repository import ConfiguredTaskRepository
from .errors import EngineError
from .management import audit_agent
from .scheduling import next_occurrence, delivery_time


def task_request(task, agent, fallback=None):
    parameters=task['parametros'] or {}
    configuration=parameters.get('_agent_configuration')
    if configuration:
        return dict(instructions=configuration['instructions'],limits=configuration['limits'],
            pipeline=[{'tool':tool,'parameters':configuration.get('tool_parameters',{}).get(tool,{})}
                      for tool in configuration['capabilities']])
    context=parameters.get('query_context')
    if context:
        # Publication destination metadata (country, city, scope, category, etc.)
        # must not influence the planner's search objective. It stays on the task
        # for the separate DPIA publication stage.
        objective=context.get('prompt') or task['nombre'] or task['tipo']
        return dict(objective=objective[:4000],limits=agent['limits'])
    if fallback:return fallback
    if task['tipo']=='PRODUCTOS_NUEVOS':
        return dict(instructions=task['nombre'] or agent['instructions'],limits=agent['limits'],
            pipeline=[{'tool':tool,'parameters':values} for tool,values in agent['search_parameters'].items()])
    return dict(objective=task['nombre'] or task['tipo'],limits=agent['limits'])


def synchronize(conn, principal, agent, task_id, *, default_schedule=None, default_request=None, now=None):
    repo=ConfiguredTaskRepository(conn)
    rows=repo.rows(agent,task_id)
    if not rows or (rows[0]['parametros'] or {}).get('_deleted_at'):
        raise EngineError('task_not_found',404)
    task=rows[0];parameters=dict(task['parametros'] or {})
    existing=repo.task_schedules(agent,task_id)
    if len(existing)>1:raise EngineError('task_schedule_conflict',409)
    previous=existing[0] if existing else None
    source=parameters.get('schedule')
    managed = previous and previous['definition'].get('configured_task_schedule')
    if managed:
        timing={key:value for key,value in previous['definition'].items() if key in SCHEDULE_CREATE['properties']}
        timing['timezone']=previous['timezone']
    elif source:
        frequency=source['frequency']
        timing=dict(timezone=source['timezone'],frequency='DAILY' if frequency=='daily' else 'WEEKLY',
            weekdays=list(range(1,8)) if frequency=='daily' else sorted(day or 7 for day in source['days']),
            execution_time=source['time'],delivery_time=source['time'],dst_policy='REJECT_AMBIGUOUS_OR_NONEXISTENT')
        if frequency not in ('daily','twice','weekly'):raise EngineError('invalid_task_schedule',422)
    elif previous:
        timing={key:value for key,value in previous['definition'].items() if key in SCHEDULE_CREATE['properties']}
        timing['timezone']=previous['timezone']
    elif default_schedule:
        timing=dict(default_schedule)
    else:
        original=repo.original_schedule(agent)
        if not original:raise EngineError('task_schedule_missing',409)
        timing=dict(timezone=original['zona_horaria'],frequency='DAILY' if original['frecuencia']=='DIARIA' else 'WEEKLY',
            weekdays=original['dias_semana'],execution_time=original['hora_local'].isoformat()[:5],
            delivery_time=original['hora_local'].isoformat()[:5],dst_policy='REJECT_AMBIGUOUS_OR_NONEXISTENT')
    validate(SCHEDULE_CREATE,timing)
    request=task_request(task,agent,default_request if task['tipo']=='PRODUCTOS_NUEVOS' else None)
    validate(REQUEST_CREATE,request)
    from .dispatcher import request_hash, validate_request_budget
    from .execution_manager import automatic_request
    request=automatic_request(agent,request)
    validate_request_budget(agent,{**request,'pipeline':[]})
    definition={**timing,'request':request,'request_hash':request_hash(request),
                'author':{'kind':'SESSION','actor_id':str(agent['owner_id'])}}
    if managed:definition['configured_task_schedule']=True
    enabled=bool(task['habilitada']) and (bool(previous['enabled']) if managed else True);now=now or now_utc()
    unchanged=previous and previous['definition']==definition and previous['timezone']==timing['timezone'] and bool(previous['enabled'])==enabled
    # Preserve an already-due slot on idempotent synchronization; never postpone it.
    due=previous['next_run_at'] if unchanged or (managed and bool(previous['enabled'])==enabled) else next_occurrence(timing,now) if enabled else None
    if enabled and due is None:enabled=False
    if enabled:delivery_time(timing,due)
    identifier=previous['id'] if previous else str(uuid5(NAMESPACE_URL,'pwa-task-schedule:'+agent['id']+':'+str(task_id)))
    if not unchanged:
        values=dict(timezone=timing['timezone'],definition=definition,enabled=enabled,next_run_at=due,
                    legacy_task_id=task_id,revision=previous['revision']+1 if previous else 1)
        if not previous:values.update(id=identifier,owner_id=agent['owner_id'],agent_id=agent['id'],created_at=now)
        repo.persist_schedule(values,previous)
        audit_agent(conn,principal,agent,'TASK_SCHEDULE_UPDATED' if previous else 'TASK_SCHEDULE_CREATED',
                    {'schedule_id':identifier,'legacy_task_id':task_id,'enabled':enabled},now)
    if not source and not managed:
        parameters['schedule']=dict(frequency='daily' if timing['frequency']=='DAILY' else 'twice' if len(timing['weekdays'])==2 else 'weekly',
            days=[] if timing['frequency']=='DAILY' else sorted(day%7 for day in timing['weekdays']),
            time=timing['execution_time'],timezone=timing['timezone'])
    repo.bind_task(task,agent,parameters)
    repo.retire_general_pwa_schedule(agent)
    return {'id':identifier,'legacy_task_id':task_id,'enabled':enabled,'next_run_at':due.isoformat() if due else None}


def schedules_for_task(conn, agent, task_id):
    """Persisted schedules only. Never infer a general agent schedule for a task."""
    from sqlalchemy import select, func
    from . import models as m
    from .contracts import iso
    from .dispatcher import public_schedule
    items = []
    for row in ConfiguredTaskRepository(conn).task_schedules(agent, task_id):
        last = conn.execute(select(func.max(m.jobs.c.started_at)).where(
            m.jobs.c.owner_id == agent['owner_id'], m.jobs.c.agent_id == agent['id'],
            m.jobs.c.schedule_id == row['id'], m.jobs.c.legacy_task_id == task_id)).scalar()
        failure=conn.execute(select(m.agent_events.c.created_at,m.agent_events.c.details).where(
            m.agent_events.c.owner_id==agent['owner_id'],m.agent_events.c.agent_id==agent['id'],
            m.agent_events.c.action=='SCHEDULE_RUN_FAILED',
            m.agent_events.c.details['schedule_id'].as_string()==row['id'])
            .order_by(m.agent_events.c.created_at.desc(),m.agent_events.c.id.desc()).limit(1)).mappings().first()
        items.append({**public_schedule(row), 'last_run_at': iso(last),
            'last_failure':{'at':iso(failure['created_at']),'reason_code':(failure['details'] or {}).get('reason_code')} if failure else None})
    return items


def scheduled_tasks(conn, agent):
    return [dict(id=row['id'], name=row['nombre'] or row['tipo'], enabled=bool(row['habilitada']),
                 schedules=schedules_for_task(conn, agent, row['id']))
            for row in ConfiguredTaskRepository(conn).rows(agent)
            if not (row['parametros'] or {}).get('_deleted_at')]


def save_task_schedule(conn, principal, agent, task, command, *, now=None):
    """Edit one task's schedule with existing persistence, request and time services."""
    from .contracts import TASK_SCHEDULE_UPDATE
    from .dispatcher import request_hash, validate_request_budget
    validate(TASK_SCHEDULE_UPDATE, command)
    principal.require('jobs:create')
    repo = ConfiguredTaskRepository(conn)
    existing = repo.task_schedules(agent, task['id'])
    if len(existing) > 1:raise EngineError('task_schedule_conflict',409)
    previous = existing[0] if existing else None
    if command['expected_revision'] != (previous['revision'] if previous else 0):
        raise EngineError('revision_conflict',409)
    if command['enabled'] and not task['habilitada']:raise EngineError('task_paused',409)
    timing = {key:value for key,value in command.items() if key not in ('enabled','expected_revision')}
    now = now or now_utc()
    # Validate DST and date even when disabled, but permit expired disabled one-offs.
    previous_timing = {key:value for key,value in (previous['definition'] if previous else {}).items() if key in SCHEDULE_CREATE['properties']}
    same_timing = previous and previous_timing == timing and previous['enabled'] == command['enabled']
    due = previous['next_run_at'] if same_timing else next_occurrence(timing, now)
    if command['enabled'] and due is None:raise EngineError('execution_time_in_past',422)
    if due is not None:delivery_time(timing,due)
    request = task_request(task,agent)
    validate(REQUEST_CREATE,request)
    from .execution_manager import automatic_request
    request=automatic_request(agent,request)
    validate_request_budget(agent,{**request,'pipeline':[]})
    if any(step['tool'].startswith('mcp.') for step in request.get('pipeline',[])):
        principal.require('mcp:execute')
    definition = {**timing,'request':request,'request_hash':request_hash(request),
                  'author':{'kind':principal.kind,'actor_id':principal.actor_id},'configured_task_schedule':True}
    # Task saves with unchanged timing must not postpone a due occurrence.
    if previous and previous['definition'] == definition and previous['enabled'] == command['enabled']:
        return previous
    values = dict(timezone=timing['timezone'],definition=definition,enabled=command['enabled'],
        next_run_at=due if command['enabled'] else None, legacy_task_id=task['id'],
        revision=previous['revision']+1 if previous else 1)
    if not previous:
        values.update(id=str(uuid5(NAMESPACE_URL,'pwa-task-schedule:'+agent['id']+':'+str(task['id']))),
                      owner_id=agent['owner_id'],agent_id=agent['id'],created_at=now)
    repo.persist_schedule(values,previous)
    audit_agent(conn,principal,agent,'TASK_SCHEDULE_UPDATED' if previous else 'TASK_SCHEDULE_CREATED',
                {'schedule_id':previous['id'] if previous else values['id'],
                 'legacy_task_id':task['id'],'enabled':command['enabled']},now)
    return {**(previous or {}),**values}
