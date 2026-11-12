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
    if source:
        frequency=source['frequency']
        timing=dict(timezone=source['timezone'],frequency='DAILY' if frequency=='daily' else 'WEEKLY',
            weekdays=list(range(1,8)) if frequency=='daily' else sorted(day or 7 for day in source['days']),
            execution_time=source['time'],delivery_time=source['time'],dst_policy='REJECT_AMBIGUOUS_OR_NONEXISTENT')
        if frequency not in ('daily','twice','weekly'):raise EngineError('invalid_task_schedule',422)
    elif previous:
        timing={key:previous['definition'][key] for key in SCHEDULE_CREATE['properties']}
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
    from .dispatcher import request_hash
    definition={**timing,'request':request,'request_hash':request_hash(request),
                'author':{'kind':'SESSION','actor_id':str(agent['owner_id'])}}
    enabled=bool(task['habilitada']);now=now or now_utc()
    unchanged=previous and previous['definition']==definition and previous['timezone']==timing['timezone'] and bool(previous['enabled'])==enabled
    # Preserve an already-due slot on idempotent synchronization; never postpone it.
    due=previous['next_run_at'] if unchanged else next_occurrence(timing,now) if enabled else None
    if enabled:delivery_time(timing,due)
    identifier=previous['id'] if previous else str(uuid5(NAMESPACE_URL,'pwa-task-schedule:'+agent['id']+':'+str(task_id)))
    if not unchanged:
        values=dict(timezone=timing['timezone'],definition=definition,enabled=enabled,next_run_at=due,
                    legacy_task_id=task_id,revision=previous['revision']+1 if previous else 1)
        if not previous:values.update(id=identifier,owner_id=agent['owner_id'],agent_id=agent['id'],created_at=now)
        repo.persist_schedule(values,previous)
        audit_agent(conn,principal,agent,'TASK_SCHEDULE_UPDATED' if previous else 'TASK_SCHEDULE_CREATED',
                    {'schedule_id':identifier,'legacy_task_id':task_id,'enabled':enabled},now)
    if not source:
        parameters['schedule']=dict(frequency='daily' if timing['frequency']=='DAILY' else 'twice' if len(timing['weekdays'])==2 else 'weekly',
            days=[] if timing['frequency']=='DAILY' else sorted(day%7 for day in timing['weekdays']),
            time=timing['execution_time'],timezone=timing['timezone'])
    repo.bind_task(task,agent,parameters)
    repo.retire_general_pwa_schedule(agent)
    return {'id':identifier,'legacy_task_id':task_id,'enabled':enabled,'next_run_at':due.isoformat() if due else None}
