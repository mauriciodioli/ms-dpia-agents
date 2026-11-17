"""Explicit review capability; the legacy evidence-approval API is unchanged."""
from flask import request
from .api import api, endpoint, arguments, identifier, json_body, engine_write
from .result_channels import project
from .result_assessment import review
from .errors import EngineError


@api.route('/jobs/<job_id>/assessment',methods=['GET','POST'])
@endpoint('results:read',write=True)
def result_assessment(conn,principal,repo,job_id):
    arguments();principal.require('jobs:read')
    job=repo.job(identifier(job_id))
    if request.method=='GET':return {'assessment':project(conn,repo,job)}
    principal.require('results:review')
    engine_write(principal)
    body=json_body()
    if set(body)-{'result_id','decision','reason'} or not {'result_id','decision'}<=set(body):raise EngineError('invalid_contract')
    project(conn,repo,job) # identical visibility and delivery timing for all channels
    review(conn,principal,job['id'],identifier(body['result_id']),body['decision'],body.get('reason',''))
    return {'assessment':project(conn,repo,repo.job(job['id']))}


@api.route('/jobs/<job_id>/task',methods=['GET','PATCH','DELETE'])
@endpoint('results:read',write=True)
def result_task_action(conn,principal,repo,job_id):
    from .result_channels import task_action
    arguments();principal.require('jobs:read')
    job=repo.job(identifier(job_id))
    action={'GET':'inspect','PATCH':'update','DELETE':'remove'}[request.method]
    configuration=None
    if request.method!='GET':
        principal.require('agents:write');engine_write(principal)
        body=json_body()
        if action=='remove':
            if set(body)!={'confirm'} or body['confirm'] is not True:raise EngineError('confirmation_required')
        else:
            if set(body)!={'configuration'}:raise EngineError('invalid_contract')
            configuration=body['configuration']
    return task_action(conn,principal,repo,job,action,configuration)
