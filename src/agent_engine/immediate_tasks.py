"""Queue one immediate scheduled run, only after the configured task exists."""
from uuid import UUID, uuid5, NAMESPACE_URL
from sqlalchemy import select, update, insert, Table, MetaData
from . import models as m
from .auth import active_user, Principal, SCOPES, now_utc
from .errors import EngineError
from .management import AgentManager, locked_agent, audit_agent
from .configured_task_repository import ConfiguredTaskRepository
from .task_schedules import task_request, execution_agent
from .task_sources import catalog, allowed_tools
from .tools import default_registry
from .contracts import validate, SCHEDULE_CREATE, REQUEST_CREATE, iso


def schedule_now(conn, body):
    if (set(body)!={'operation','owner_id','source_agent_id','task_id','request_id'}
            or any(type(body.get(k)) is not int or body[k]<1 for k in ('owner_id','source_agent_id','task_id'))):
        raise EngineError('invalid_contract')
    try:
        if str(UUID(body['request_id']))!=body['request_id']:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise EngineError('invalid_contract') from None
    owner=body['owner_id'];active_user(conn,owner)
    repo=ConfiguredTaskRepository(conn);repo.lock_owner(owner)
    legacy=Table('agentes',MetaData(),autoload_with=conn,resolve_fks=False)
    parent=conn.execute(select(legacy).where(legacy.c.id==body['source_agent_id'],legacy.c.usuario_id==owner).with_for_update()).mappings().first()
    if parent is None or (parent['configuracion'] or {}).get('_deleted_at'):
        raise EngineError('agent_not_found',404)
    tasks=repo.table()
    task=conn.execute(select(tasks).where(tasks.c.id==body['task_id'],tasks.c.agente_id==parent['id']).with_for_update()).mappings().first()
    if (task is None or (task['parametros'] or {}).get('_deleted_at') or
            (task['parametros'] or {}).get('immediate_request_id')!=body['request_id']):
        raise EngineError('task_not_found',404)
    principal=Principal(owner,'PWA_SERVICE','ms202611sb2b',SCOPES,True,frozenset())
    registry=default_registry(conn=conn,owner=owner)
    agent=conn.execute(select(m.agents).where(m.agents.c.owner_id==owner,m.agents.c.legacy_agent_id==parent['id']).with_for_update()).mappings().first()
    now=now_utc()
    if agent is None:
        placeholder={'id':'00000000-0000-0000-0000-000000000000','owner_id':owner}
        sources=catalog(conn,placeholder,registry)
        capabilities=sorted({tool for source in sources for tool in source['tools']})[:16]
        if not capabilities:raise EngineError('selected_sources_unavailable',409)
        from .owner_identity import owner_email
        manager=AgentManager(conn,principal,registry=registry)
        created=manager.save(dict(name=owner_email(conn,owner),description='',
            instructions='Ejecutar únicamente las instrucciones de la tarea configurada, con sus conexiones autorizadas.',
            timezone=parent['zona_horaria'],capabilities=capabilities,
            limits=dict(max_tool_calls=4,max_output_tokens=2000,max_duration_seconds=300,max_corrections=0)))
        conn.execute(update(m.agents).where(m.agents.c.id==created['id']).values(legacy_agent_id=parent['id']))
        manager.set_enabled(created['id'],{'expected_revision':created['revision']},True)
        agent=locked_agent(conn,principal,created['id'])
    else:agent=locked_agent(conn,principal,agent['id'])
    # Resolve and validate the persisted task-to-agent binding, including nullable engine links.
    if not repo.rows(agent,body['task_id']):raise EngineError('task_not_found',404)
    identifier=str(uuid5(NAMESPACE_URL,'immediate-task:'+str(owner)+':'+body['request_id']))
    previous=conn.execute(select(m.schedules).where(m.schedules.c.id==identifier,m.schedules.c.owner_id==owner)).mappings().first()
    if previous:
        if previous['legacy_task_id']!=task['id'] or previous['agent_id']!=agent['id']:
            raise EngineError('idempotency_conflict',409)
        return response(body,agent,previous,True)
    from .pause_control import require_unpaused
    require_unpaused(conn,agent)
    if agent['configuration_state']!='ENABLED':raise EngineError('agent_disabled',409)
    effective=execution_agent(task,agent)
    allowed_tools(conn,effective,registry)  # Current source availability; never call a provider here.
    request=task_request(task,effective)
    from .execution_manager import automatic_request
    from .dispatcher import validate_request_budget, request_hash
    request=automatic_request(effective,request)
    validate(REQUEST_CREATE,request);validate_request_budget(effective,request)
    # An already-due UTC minute avoids scheduling a future recurrence or a next-day delivery.
    due=now.replace(second=0,microsecond=0)
    timing=dict(timezone='UTC',frequency='ONCE',weekdays=[],execution_date=due.date().isoformat(),
                execution_time=due.strftime('%H:%M'),delivery_time=due.strftime('%H:%M'),
                dst_policy='REJECT_AMBIGUOUS_OR_NONEXISTENT')
    validate(SCHEDULE_CREATE,timing)
    definition={**timing,'request':request,'request_hash':request_hash(request),
                'author':{'kind':'SESSION','actor_id':str(owner)},'configured_task_schedule':True}
    values=dict(id=identifier,owner_id=owner,agent_id=agent['id'],legacy_task_id=task['id'],timezone='UTC',
                definition=definition,enabled=True,revision=1,next_run_at=due,created_at=now)
    conn.execute(insert(m.schedules).values(**values))
    repo.bind_task(task,agent,dict(task['parametros'] or {}))
    conn.execute(update(tasks).where(tasks.c.id==task['id'],tasks.c.agente_id==parent['id']).values(habilitada=True,actualizado_en=now))
    audit_agent(conn,principal,agent,'TASK_SCHEDULE_CREATED',{'schedule_id':identifier,'legacy_task_id':task['id'],'enabled':True,'immediate':True},now)
    return response(body,agent,values,False)


def response(body,agent,schedule,replayed):
    return {'api_version':'agents.v1','owner_id':body['owner_id'],'source_agent_id':body['source_agent_id'],
            'task_id':body['task_id'],'request_id':body['request_id'],'replayed':replayed,
            'agent':{'id':agent['id'],'revision':agent['revision'],'configuration_state':agent['configuration_state']},
            'schedule':{'id':schedule['id'],'legacy_task_id':schedule['legacy_task_id'],
                        'enabled':schedule['enabled'],'next_run_at':iso(schedule['next_run_at'])}}
