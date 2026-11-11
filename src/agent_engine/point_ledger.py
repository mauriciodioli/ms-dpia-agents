"""Scraping reservations in the shared B2B ledger. Never initializes or tops up a wallet."""
import hashlib,json
from uuid import uuid5,NAMESPACE_URL
from sqlalchemy import select,insert,update
from services.scraping_quota import operaciones,cupos
from services.agent_configuration import agentes
from services.agent_point_status import locked_balance,period_window,context,cost
from . import models as m
from .errors import EngineError

PAID_TOOL='dpia.amazon.search'
BLOCKS=('INSUFFICIENT_POINTS','AGENT_BUDGET_EXHAUSTED','AGENT_BUDGET_MISSING','AUTOMATIC_EXECUTION_DISABLED')


def operation_id(task):return str(uuid5(NAMESPACE_URL,'dpia-agent-scraping:'+task['id']))


def policy(conn,agent):
    if agent['legacy_agent_id'] is None:return None
    source=conn.execute(select(agentes).where(agentes.c.id==agent['legacy_agent_id'],
        agentes.c.usuario_id==agent['owner_id']).with_for_update()).mappings().first()
    if not source or (source['configuracion'] or {}).get('_deleted_at'):return None
    binding=(source['configuracion'] or {}).get('engine_binding') or {}
    if source['estado']!='ACTIVO' or binding.get('id')!=agent['id']:return None
    return source


def reserve(conn,job,task,now):
    if task['tool_id']!=PAID_TOOL:return None
    agent=conn.execute(select(m.agents).where(m.agents.c.id==job['agent_id'],m.agents.c.owner_id==job['owner_id']).with_for_update()).mappings().one()
    source=policy(conn,agent)
    if not source or source['presupuesto_puntos_periodo']<1:return 'AGENT_BUDGET_MISSING'
    if job.get('schedule_id') is not None:
        activation=conn.execute(select(m.agent_events.c.details).where(m.agent_events.c.agent_id==agent['id'],
            m.agent_events.c.owner_id==agent['owner_id'],m.agent_events.c.action=='PWA_ACTIVATED')).scalar_one_or_none()
        if activation and activation.get('execution_enabled') is False:return 'AUTOMATIC_EXECUTION_DISABLED'
    try:window=period_window(source['periodo_presupuesto'],source['zona_horaria'],now)
    except (ValueError,KeyError):return 'AGENT_BUDGET_MISSING'
    total,held=locked_balance(conn,job['owner_id'])
    oid=operation_id(task)
    existing=conn.execute(select(operaciones).where(operaciones.c.operacion_id==oid).with_for_update()).mappings().first()
    fingerprint=hashlib.sha256(json.dumps(dict(agent_id=agent['id'],task_id=task['id'],parameters=task['input_snapshot']),sort_keys=True).encode()).hexdigest()
    if existing and (existing['usuario_id']!=job['owner_id'] or existing['solicitud_hash']!=fingerprint):
        raise EngineError('point_operation_conflict',409)
    if existing and existing['estado'] in ('dispatching','pending','consumed'):return 'POINT_OPERATION_NOT_REPLAYABLE'
    own_hold=existing and existing['estado']=='reserved'
    available=total-sum(cost(r) for r in held)+(1 if own_hold else 0)
    used=sum(cost(r) for r in held if r['operacion_id']!=oid and context(r).get('agent_id')==agent['id'] and context(r).get('period')==window['key'])
    reason='INSUFFICIENT_POINTS' if available<1 else 'AGENT_BUDGET_EXHAUSTED' if used>=source['presupuesto_puntos_periodo'] else None
    if reason:
        if own_hold:conn.execute(update(operaciones).where(operaciones.c.operacion_id==oid).values(estado='released',actualizado_en=now))
        return reason
    metadata=dict(agent_id=agent['id'],job_id=job['id'],task_id=task['id'],period=window['key'],
        period_start=window['start'].isoformat()+'Z',period_end=window['end'].isoformat()+'Z',billing_schema='agents.points.v1')
    values=dict(estado='reserved',contexto_json=json.dumps(metadata),actualizado_en=now)
    # Only a fenced pre-provider retry can re-arm this same logical operation, without a second debit.
    if existing:conn.execute(update(operaciones).where(operaciones.c.operacion_id==oid).values(**values))
    else:conn.execute(insert(operaciones).values(operacion_id=oid,usuario_id=job['owner_id'],solicitud_hash=fingerprint,
        origen='amazon',creado_en=now,**values))
    return None


def settle(conn,job,task,now,state):
    if task['tool_id']!=PAID_TOOL:return
    conn.execute(select(cupos.c.usuario_id).where(cupos.c.usuario_id==job['owner_id']).with_for_update()).first()
    row=conn.execute(select(operaciones).where(operaciones.c.operacion_id==operation_id(task),
        operaciones.c.usuario_id==job['owner_id']).with_for_update()).mappings().first()
    if row is None:
        if state in ('dispatching','consumed'):raise EngineError('point_reservation_required',409)
        return
    if context(row).get('task_id')!=task['id'] or context(row).get('agent_id')!=job['agent_id']:
        raise EngineError('point_operation_conflict',409)
    if row['estado'] in ('consumed','released'):
        if row['estado']==state:return
        if state in ('dispatching','consumed'):raise EngineError('point_reservation_required',409)
        return
    if state=='dispatching' and row['estado']!='reserved':raise EngineError('point_reservation_required',409)
    conn.execute(update(operaciones).where(operaciones.c.operacion_id==row['operacion_id']).values(
        estado=state,proveedor_trabajo_id=task.get('provider_job_id'),actualizado_en=now))


def settle_job(conn,job,now):
    tasks=conn.execute(select(m.tasks).where(m.tasks.c.owner_id==job['owner_id'],m.tasks.c.job_id==job['id']).with_for_update()).mappings().all()
    for task in tasks:settle(conn,job,task,now,'released' if task['provider_submission_state']=='NOT_SUBMITTED' else 'pending')


def blocked(conn,job,reason,now):
    conn.execute(update(m.jobs).where(m.jobs.c.id==job['id'],m.jobs.c.owner_id==job['owner_id']).values(error_code=reason,updated_at=now))
