"""Read-only HMAC bridge. No jobs, quotas, providers or result copies."""
from sqlalchemy import select, exists
from .api import api, engine, arguments, json_body, identifier
from .auth import Principal, active_user
from .repository import ReadRepository
from .contracts import iso
from .errors import EngineError
from .pwa_activation import verify_hmac
from . import models as m

PATH='/api/agents/v1/internal/pwa-history'


def informational_metadata(conn, job, result):
    # Same narrow eligibility as informational_delivery, without transferring JSON payloads.
    latest=conn.execute(select(m.results.c.id).where(m.results.c.owner_id==job['owner_id'],
        m.results.c.job_id==job['id']).order_by(m.results.c.version.desc()).limit(1)).scalar_one_or_none()
    if latest!=result['id'] or result['evidence_status']!='UNVERIFIED':return False
    tasks=conn.execute(select(m.tasks.c.id,m.tasks.c.tool_id,m.tasks.c.state).where(
        m.tasks.c.owner_id==job['owner_id'],m.tasks.c.job_id==job['id']).order_by(m.tasks.c.position)).mappings().all()
    if not tasks or any(t['tool_id']!='dpia.amazon.search' or t['state']!='COMPLETED' for t in tasks):return False
    if conn.execute(select(m.reviews.c.id).where(m.reviews.c.owner_id==job['owner_id'],m.reviews.c.job_id==job['id'])).first():return False
    return bool(conn.execute(select(exists().where(m.tasks.c.id==tasks[-1]['id'],
        m.tasks.c.owner_id==job['owner_id'],m.results.c.id==result['id'],
        m.results.c.owner_id==job['owner_id'],m.tasks.c.output==m.results.c.payload))).scalar())


@api.post('/internal/pwa-history')
def pwa_history():
    verify_hmac(PATH);arguments();body=json_body()
    if (set(body) not in ({'owner_id','offset'},{'owner_id','job_id'})
            or type(body.get('owner_id')) is not int or body['owner_id']<1):raise EngineError('invalid_contract')
    with engine().connect() as conn:
        owner=body['owner_id'];active_user(conn,owner)
        principal=Principal(owner,'PWA_SERVICE','ms202611sb2b',frozenset({'agents:read','jobs:read','results:read'}),True,frozenset())
        repo=ReadRepository(conn,principal)
        if 'job_id' in body:
            job_id=identifier(body['job_id']);result=repo.result(job_id)
            job=repo.job(job_id);agent=repo.agent(job['agent_id'])
            from .owner_identity import owner_email
            name=owner_email(conn,owner) if agent['legacy_agent_id'] is not None else agent['name']
            response=dict(api_version='agents.v1',owner_id=owner,agent_name=name,**result)
            if job['schedule_id']:
                current=conn.execute(select(m.schedule_current.c.last_checked_at,
                    m.schedule_current.c.last_changed_at,m.schedule_current.c.version).where(
                    m.schedule_current.c.owner_id==owner,
                    m.schedule_current.c.schedule_id==job['schedule_id'],
                    m.schedule_current.c.latest_job_id==job_id)).mappings().first()
                if current:
                    response.update(last_checked_at=iso(current['last_checked_at']),
                        last_changed_at=iso(current['last_changed_at']),
                        schedule_version=current['version'])
            return response
        offset=body['offset']
        if type(offset) is not int or not 0<=offset<=999999:raise EngineError('invalid_contract')
        # Scan a bounded batch; only lightweight jobs/names are fetched. The result
        # policy is shared with the detail endpoint, including delivery availability.
        candidates=conn.execute(select(m.jobs.c.id,m.jobs.c.agent_id,m.jobs.c.finished_at,m.jobs.c.created_at,
            m.jobs.c.owner_id,m.jobs.c.revision,m.jobs.c.state,m.jobs.c.schedule_id,m.jobs.c.deliver_not_before,m.agents.c.name,m.agents.c.legacy_agent_id).join(m.agents,
                (m.agents.c.id==m.jobs.c.agent_id)&(m.agents.c.owner_id==m.jobs.c.owner_id)).where(
                m.jobs.c.owner_id==owner,m.jobs.c.state=='DELIVERED',repo.agent_filter())
            .order_by(m.jobs.c.created_at.desc(),m.jobs.c.id).offset(offset).limit(25)).mappings().all()
        items=[]
        for candidate in candidates[:24]:
            refresh=None
            if candidate['schedule_id']:
                refresh=conn.execute(select(m.schedule_current.c.latest_job_id,
                    m.schedule_current.c.last_checked_at,m.schedule_current.c.last_changed_at,
                    m.schedule_current.c.version).where(
                    m.schedule_current.c.owner_id==owner,
                    m.schedule_current.c.schedule_id==candidate['schedule_id'])).mappings().first()
                # Only the latest successful scheduled result appears as a history card.
                if refresh and refresh['latest_job_id']!=candidate['id']:
                    continue
            try:
                job,query=repo._delivered_result_query(candidate)
                result=conn.execute(query.with_only_columns(m.results.c.id,m.results.c.approved_at,
                    m.results.c.evidence_status)).mappings().first()
                if not result or (result['approved_at'] is None and not informational_metadata(conn,job,result)):continue
            except EngineError as exc:
                if exc.code in ('result_not_delivered','agent_not_found'):continue
                raise
            from .owner_identity import owner_email
            name=owner_email(conn,owner) if candidate['legacy_agent_id'] is not None else candidate['name']
            item=dict(operation_id=candidate['id'],agent_id=candidate['agent_id'],agent_name=name,
                query='Respuesta de Agente',source='agents',state='consumed',product_count=None,
                created_at=iso(candidate['finished_at'] or candidate['created_at']))
            if refresh:
                item.update(last_checked_at=iso(refresh['last_checked_at']),
                    last_changed_at=iso(refresh['last_changed_at']),
                    schedule_version=refresh['version'])
            items.append(item)
        return dict(api_version='agents.v1',owner_id=owner,operations=items,
            has_more=len(candidates)>24,next_offset=offset+min(24,len(candidates)))
