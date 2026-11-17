"""One authorized projection of persisted assessments for API and the PWA bridge."""
from .result_assessment import inspect, REVIEWABLE
from .repository import public_job
from .contracts import RESULT, validate
from .auth import now_utc
from .errors import EngineError


def project(conn,repo,job):
    data=inspect(conn,job)
    data.update(agent_id=job['agent_id'],task_id=job['legacy_task_id'],execution=public_job(job))
    if job['state']=='FAILED':return data
    if job['state']=='DELIVERED':
        delivered=repo.result(job['id'])
        return {**data,**delivered}
    stored=job['configuration_snapshot'].get('result_assessment',{})
    if (job['state']!='REVIEWING' or not stored or stored.get('result_id')!=data['result_id']
            or data['result_classification'] not in REVIEWABLE|{'NO_MATCH'}
            or (job['deliver_not_before'] is not None and job['deliver_not_before']>now_utc())):
        raise EngineError('result_not_delivered',409)
    validate(RESULT,data['result'])
    return data


def task_action(conn,principal,repo,job,action,configuration=None):
    from .configured_tasks import ConfiguredTaskManager
    from .result_assessment import remove_no_match
    data=project(conn,repo,job)
    if data['result_classification']!='NO_MATCH' or not job['legacy_task_id']:raise EngineError('no_match_task_required',409)
    if action not in ('inspect','update','remove') or (action!='update' and configuration is not None):raise EngineError('invalid_contract')
    principal.require('agents:read')
    if action=='remove':return remove_no_match(conn,principal,job)
    if action=='update' and not isinstance(configuration,dict):raise EngineError('invalid_contract')
    return {'task':ConfiguredTaskManager(conn,principal).detail(job['agent_id'],job['legacy_task_id'],body=configuration if action=='update' else None)}
