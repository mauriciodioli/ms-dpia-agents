"""Transactional logical deletion. Retains history, FKs and independent audit."""
import json
from dataclasses import replace
from uuid import UUID
from sqlalchemy import MetaData, Table, select, update, insert, inspect
from . import models as m
from .auth import now_utc
from .errors import EngineError
from .repository import agent_access
from .state_store import transition_job


def legacy_agent(conn, source_id, owner, native_id, source_revision=None):
    schema=inspect(conn);metadata=MetaData()
    names=('agentes','agente_tareas','agente_programaciones','agente_ejecuciones')
    tables={name:Table(name,metadata,autoload_with=conn,resolve_fks=False) for name in names if schema.has_table(name)}
    if not {'agentes','agente_tareas','agente_programaciones'}.issubset(tables):
        raise EngineError('shared_legacy_storage_required',503)
    base=tables['agentes']
    row=conn.execute(select(base).where(base.c.id==source_id,base.c.usuario_id==owner).with_for_update()).mappings().first()
    if row is None:raise EngineError('source_agent_mismatch',409)
    if source_revision is not None and row['version_config']!=source_revision:raise EngineError('revision_conflict',409)
    config=row['configuracion'] or {};binding=config.get('engine_binding')
    if binding and binding.get('id')!=native_id:raise EngineError('source_agent_mismatch',409)
    if config.get('_deleted_at'):raise EngineError('source_agent_deleted',409)
    if 'agente_ejecuciones' in tables:
        executions=conn.execute(select(tables['agente_ejecuciones']).where(
            tables['agente_ejecuciones'].c.agente_id==source_id).with_for_update()).mappings().all()
        if any(e['estado'] not in ('PENDIENTE','COMPLETADA','PARCIAL','FALLIDA','CANCELADA') or
            (e['estado']=='PENDIENTE' and (e.get('iniciada_en') is not None or e.get('puntos_reservados',0))) for e in executions):
            raise EngineError('agent_has_active_jobs',409)
    return tables,row


def delete_agent(conn, principal, agent_id, body, *, interface='agents', source_id=None, source_revision=None, draft=False):
    principal.require('agents:delete')
    if (not isinstance(body,dict) or set(body)!={'confirm','expected_revision','operation_id'} or body['confirm'] is not True
            or type(body['expected_revision']) is not int or body['expected_revision']<1):
        raise EngineError('invalid_contract')
    try:
        if str(UUID(body['operation_id']))!=body['operation_id']:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise EngineError('invalid_operation_id') from None
    administrative=principal.kind=='SESSION' and principal.admin
    tombstone=conn.execute(select(m.agent_deletions).where(m.agent_deletions.c.agent_id==agent_id)).mappings().first()
    if tombstone:
        allowed=administrative or tombstone['owner_id']==principal.owner_id
        if principal.kind=='API_CLIENT' and not principal.all_agents:
            allowed=allowed and principal.actor_id in tombstone['snapshot'].get('client_ids',[])
        if not allowed:raise EngineError('agent_not_found',404)
        if source_id is not None and tombstone['legacy_agent_id']!=source_id:raise EngineError('source_agent_mismatch',403)
        return tombstone
    scoped=principal
    if administrative:
        owner=conn.execute(select(m.agents.c.owner_id).where(m.agents.c.id==agent_id)).scalar_one_or_none()
        if owner is not None:scoped=replace(principal,owner_id=owner,all_agents=True,agent_ids=frozenset())
    row=conn.execute(select(m.agents).where(m.agents.c.id==agent_id,m.agents.c.owner_id==scoped.owner_id,
        agent_access(scoped)).with_for_update()).mappings().first()
    if row is None and not draft:raise EngineError('agent_not_found',404)
    if row and row['revision']!=body['expected_revision']:raise EngineError('revision_conflict',409)
    owner=row['owner_id'] if row else principal.owner_id
    source=row['legacy_agent_id'] if row else source_id
    if source_id is not None and source!=source_id:raise EngineError('source_agent_mismatch',403)
    legacy=legacy_agent(conn,source,owner,agent_id if row else None,source_revision) if source is not None else None
    jobs=conn.execute(select(m.jobs).where(m.jobs.c.agent_id==agent_id,m.jobs.c.owner_id==owner).with_for_update()).mappings().all() if row else []
    if any(j['state'] not in ('CREATED','SCHEDULED','QUEUED','DELIVERED','FAILED','CANCELLED') or
           (j['state'] in ('CREATED','SCHEDULED','QUEUED') and j['started_at'] is not None) for j in jobs):
        raise EngineError('agent_has_active_jobs',409)
    ids=[j['id'] for j in jobs]
    tasks=conn.execute(select(m.tasks).where(m.tasks.c.owner_id==owner,m.tasks.c.job_id.in_(ids)).with_for_update()).mappings().all()
    if any(t['state'] not in ('PENDING','WAITING_DEPENDENCY','COMPLETED','FAILED','CANCELLED') or
           (t['state']=='PENDING' and t['provider_submission_state']!='NOT_SUBMITTED') for t in tasks):
        raise EngineError('agent_has_active_jobs',409)
    now=now_utc()
    for job in jobs:
        if job['state'] in ('CREATED','SCHEDULED','QUEUED'):
            transition_job(conn,owner_id=owner,job_id=job['id'],expected_revision=job['revision'],target='CANCELLED',
                actor_id=principal.actor_id,actor_type=principal.kind,reason_code='AGENT_DELETED',now=now)
    conn.execute(update(m.tasks).where(m.tasks.c.owner_id==owner,m.tasks.c.job_id.in_(ids),
        m.tasks.c.state.in_(['PENDING','WAITING_DEPENDENCY'])).values(state='CANCELLED'))
    conn.execute(update(m.schedules).where(m.schedules.c.owner_id==owner,m.schedules.c.agent_id==agent_id).values(
        enabled=False,next_run_at=None,revision=m.schedules.c.revision+1))
    from .inbox import inbox
    if inspect(conn).has_table(inbox.name):
        conn.execute(update(inbox).where(inbox.c.owner_id==owner,inbox.c.agent_id==agent_id,inbox.c.state=='PENDING').values(
            state='REJECTED',error_code='AGENT_DELETED',processed_at=now))
    audit=dict(agent_id=agent_id,owner_id=owner,legacy_agent_id=source,operation_id=body['operation_id'],
        actor_type=principal.kind,actor_id=principal.actor_id,interface=interface,deleted_at=now,
        snapshot=dict(agent=dict(row) if row else None,source_revision=legacy[1]['version_config'] if legacy else None,
          legacy_configuration=legacy[1]['configuracion'] if legacy else None,
          client_ids=list(conn.execute(select(m.client_grants.c.client_id).where(
              m.client_grants.c.owner_id==owner,m.client_grants.c.agent_id==agent_id)).scalars())))
    audit['snapshot']=json.loads(json.dumps(audit['snapshot'],default=str))
    conn.execute(insert(m.agent_deletions).values(**audit))
    if row:conn.execute(update(m.agents).where(m.agents.c.id==agent_id,m.agents.c.owner_id==owner).values(
        configuration_state='DISABLED',legacy_agent_id=None,revision=row['revision']+1,updated_at=now))
    if legacy:
        tables,old=legacy
        config={**old['configuracion'],'_deleted_at':now.isoformat(),'engine_binding':None}
        conn.execute(update(tables['agentes']).where(tables['agentes'].c.id==source,tables['agentes'].c.usuario_id==owner).values(
            estado='INACTIVO',configuracion=config,activado_en=None,actualizado_en=now))
        conn.execute(update(tables['agente_tareas']).where(tables['agente_tareas'].c.agente_id==source).values(habilitada=False))
        conn.execute(update(tables['agente_programaciones']).where(tables['agente_programaciones'].c.agente_id==source).values(
            activa=False,proxima_ejecucion_en=None))
        if 'agente_ejecuciones' in tables:
            table=tables['agente_ejecuciones']
            conn.execute(update(table).where(table.c.agente_id==source,table.c.estado=='PENDIENTE').values(estado='CANCELADA'))
    return audit
