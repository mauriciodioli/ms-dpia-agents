"""Central admin-only conversion policy in the existing integration settings store."""
from uuid import uuid4
from flask import request
from sqlalchemy import select, insert, update
from .api import api, endpoint, arguments, json_body
from .auth import now_utc, require_session_write
from .integration_models import integrations, audit
from .video_costs import positive
from .errors import EngineError

KEY='video-cost-policy'


def load(conn):
    row=conn.execute(select(integrations).where(integrations.c.id==KEY)).mappings().first()
    return {'usd_per_credit':row['config'].get('usd_per_credit') if row else None,
            'revision':row['revision'] if row else 0,
            'heygen_tariffs':row['config'].get('heygen_tariffs',[]) if row else []}


@api.route('/admin/video-cost-policy', methods=['GET','PUT'])
@endpoint(admin_only=True, write=True)
def video_cost_policy(conn, principal, repo):
    arguments()
    if request.method=='GET':return {'policy':load(conn)}
    require_session_write(principal,'manage-integrations')
    body=json_body()
    if (not isinstance(body,dict) or not {'expected_revision','usd_per_credit'}<=set(body) or set(body)-{'expected_revision','usd_per_credit','heygen_tariffs'}
            or type(body['expected_revision']) is not int):raise EngineError('invalid_contract')
    # Lock the existing owner row as well, including the first insert case.
    from model.usuario import Usuario
    conn.execute(select(Usuario.id).where(Usuario.id==principal.owner_id).with_for_update()).first()
    row=conn.execute(select(integrations).where(integrations.c.id==KEY).with_for_update()).mappings().first()
    revision=row['revision'] if row else 0
    if body['expected_revision']!=revision:raise EngineError('revision_conflict',409)
    rate=None if body['usd_per_credit'] is None else str(positive(body['usd_per_credit'],'VIDEO_COST_RATE_NOT_CONFIGURED'))
    from .video_estimates import validate_tariffs
    tariffs=validate_tariffs(body.get('heygen_tariffs',row['config'].get('heygen_tariffs',[]) if row else []))
    values=dict(config={'usd_per_credit':rate,'heygen_tariffs':tariffs},credential_ciphertext=None,enabled=rate is not None,
                revision=revision+1,diagnostic={},updated_at=now_utc())
    if row:conn.execute(update(integrations).where(integrations.c.id==KEY).values(**values))
    else:conn.execute(insert(integrations).values(id=KEY,**values))
    conn.execute(insert(audit).values(id=str(uuid4()),integration_id=KEY,actor_id=principal.actor_id,
        action='VIDEO_COST_POLICY_UPDATED',revision=revision+1,created_at=now_utc()))
    return {'policy':load(conn)}


@api.post('/admin/jobs/<job_id>/video-cost-reconciliation')
@endpoint(admin_only=True,write=True)
def reconcile_video_cost(conn,principal,repo,job_id):
    from .api import identifier
    from . import models as m
    from .video_costs import reconcile
    from .result_consolidation import consolidate
    from .management import audit_agent
    from urllib.parse import urlsplit
    arguments();require_session_write(principal,'manage-integrations')
    body=json_body()
    if (not isinstance(body,dict) or set(body)!={'result_id','remote_id','actual_usd','reference'}
            or not all(isinstance(body[k],str) for k in body)):
        raise EngineError('invalid_contract')
    ref=urlsplit(body['reference'])
    if ref.scheme!='https' or not ref.hostname or ref.username or ref.password or ref.query or ref.fragment or len(body['reference'])>2000:
        raise EngineError('invalid_contract')
    job=conn.execute(select(m.jobs).where(m.jobs.c.id==identifier(job_id)).with_for_update()).mappings().first()
    if not job:raise EngineError('job_not_found',404)
    task=conn.execute(select(m.tasks).where(m.tasks.c.job_id==job['id'],m.tasks.c.owner_id==job['owner_id'],
        m.tasks.c.tool_id=='dpia.video.produce',m.tasks.c.state=='COMPLETED').with_for_update()).mappings().first()
    result=conn.execute(select(m.results).where(m.results.c.job_id==job['id'],m.results.c.owner_id==job['owner_id']).order_by(m.results.c.version.desc()).limit(1).with_for_update()).mappings().first()
    if not task or not result or result['id']!=body['result_id']:raise EngineError('revision_conflict',409)
    output=dict(task['output']);video=dict(output.get('video') or {})
    if video.get('remote_id')!=body['remote_id']:raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
    old=video['cost']
    if old.get('reconciliation')=='CONFIRMED':
        if old.get('actual_usd')!=body['actual_usd'] or old.get('confirmation_reference')!=body['reference']:
            raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
        return {'cost':old}
    settled=reconcile(conn,job['owner_id'],old,body['actual_usd'],now_utc())
    video['cost']={**old,**settled,'reconciliation':'CONFIRMED',
        'confirmation_source':'ADMIN_PROVIDER_DOCUMENT','confirmation_reference':body['reference']}
    output['video']=video
    conn.execute(update(m.tasks).where(m.tasks.c.id==task['id'],m.tasks.c.owner_id==job['owner_id']).values(output=output))
    outputs=conn.execute(select(m.tasks.c.output).where(m.tasks.c.job_id==job['id'],m.tasks.c.owner_id==job['owner_id'],m.tasks.c.state=='COMPLETED').order_by(m.tasks.c.position)).scalars().all()
    canonical=consolidate(outputs)
    conn.execute(update(m.results).where(m.results.c.id==result['id'],m.results.c.owner_id==job['owner_id']).values(payload=canonical))
    agent=conn.execute(select(m.agents).where(m.agents.c.id==job['agent_id'],m.agents.c.owner_id==job['owner_id'])).mappings().one()
    audit_agent(conn,principal,agent,'VIDEO_COST_RECONCILED',{'job_id':job['id'],'result_id':result['id'],
        'remote_id':body['remote_id'],'confirmation_reference':body['reference']},now_utc())
    return {'cost':video['cost']}
