"""Session-only workspace surface for stage 1; public/PWA APIs are unchanged."""
from flask import request
from .api import admin, endpoint, arguments, identifier, json_body, engine_write
from .errors import EngineError
from .result_assessment import inspect, review


@admin.route('/workspace/executions/<job_id>/assessment', methods=['GET','POST'])
@endpoint('jobs:read',write=True)
def execution_assessment(conn,principal,repo,job_id):
    arguments()
    if principal.kind!='SESSION':raise EngineError('reviewer_session_required',403)
    principal.require('results:read')
    job=repo.job(identifier(job_id))
    if request.method=='POST':
        engine_write(principal)
        body=json_body()
        if set(body)!={'result_id','decision','reason'}:raise EngineError('invalid_contract')
        return {'assessment':review(conn,principal,job['id'],identifier(body['result_id']),body['decision'],body['reason'])}
    data=inspect(conn,job)
    from .video_result_url import refresh
    data=refresh(conn,job,data)
    data['agent_id']=job['agent_id'];data['task_id']=job['legacy_task_id']
    return {'assessment':data}


@admin.post('/workspace/executions/<job_id>/remove-no-match-task')
@endpoint('agents:write',write=True)
def remove_no_match_task(conn,principal,repo,job_id):
    from sqlalchemy import select,update
    from . import models as m
    from .auth import now_utc
    from .contracts import iso
    from .configured_tasks import ConfiguredTaskManager
    from .management import audit_agent
    arguments();engine_write(principal)
    if principal.kind!='SESSION':raise EngineError('reviewer_session_required',403)
    job=repo.job(identifier(job_id))
    body=json_body()
    if set(body)!={'confirm'} or body['confirm'] is not True:raise EngineError('confirmation_required')
    from .result_assessment import remove_no_match
    return remove_no_match(conn,principal,job)
