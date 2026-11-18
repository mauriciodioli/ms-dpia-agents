"""Session/API controllers for existing configured tasks and agent identity."""
from .api import api, endpoint, arguments, identifier, json_body, engine_write
from .configured_tasks import ConfiguredTaskManager
from .management import AgentManager
from .errors import EngineError


@api.get('/agents/<agent_id>/configured-tasks')
@endpoint('agents:read', write=True)
def list_configured_tasks(conn, principal, repo, agent_id):
    arguments()
    return {'items': ConfiguredTaskManager(conn, principal).listing(identifier(agent_id))}


@api.route('/agents/<agent_id>/configured-tasks/<int:task_id>', methods=['GET','PATCH'])
@api.route('/admin/agents/<agent_id>/configured-tasks/<int:task_id>', methods=['GET','PATCH'])
@endpoint('agents:read', write=True)
def configured_task(conn, principal, repo, agent_id, task_id):
    from flask import request
    arguments(('schedule_preview',) if request.method == 'GET' else ())
    administrative = request.path.startswith('/api/agents/v1/admin/')
    if 'schedule_preview' in request.args:
        import json
        try:command=json.loads(request.args['schedule_preview'])
        except (ValueError,TypeError):raise EngineError('invalid_contract') from None
        return {'preview':ConfiguredTaskManager(conn,principal).preview_schedule(identifier(agent_id),task_id,command,administrative=administrative)}
    body = None
    if request.method == 'PATCH':
        engine_write(principal)
        body = json_body()
    return {'task': ConfiguredTaskManager(conn, principal).detail(identifier(agent_id), task_id,
                  administrative=administrative, body=body)}


@api.get('/admin/configured-tasks')
@endpoint(admin_only=True)
def admin_configured_tasks(conn, principal, repo):
    from flask import request
    arguments(('limit','after'))
    try:
        limit = int(request.args.get('limit','25'))
        after = int(request.args.get('after','0'))
        if not 1 <= limit <= 100 or after < 0:
            raise ValueError()
    except ValueError:
        raise EngineError('invalid_page') from None
    return ConfiguredTaskManager(conn, principal).administration(limit, after)


@api.patch('/agents/<agent_id>/identity')
@endpoint('agents:write', write=True)
def update_identity(conn, principal, repo, agent_id):
    arguments()
    engine_write(principal)
    return {'agent': AgentManager(conn, principal).save_identity(json_body(), identifier(agent_id))}


@api.patch('/agents/<agent_id>/configured-tasks/<int:task_id>/schedule')
@api.patch('/admin/agents/<agent_id>/configured-tasks/<int:task_id>/schedule')
@endpoint('agents:write', write=True)
def update_configured_task_schedule(conn, principal, repo, agent_id, task_id):
    from flask import request
    arguments()
    engine_write(principal)
    return {'task':ConfiguredTaskManager(conn,principal).update_schedule(identifier(agent_id),task_id,json_body(),
        administrative=request.path.startswith('/api/agents/v1/admin/'))}


@api.route('/agents/<agent_id>/configured-tasks/<int:task_id>/video/<section>', methods=['GET', 'PATCH'])
@api.route('/admin/agents/<agent_id>/configured-tasks/<int:task_id>/video/<section>', methods=['GET', 'PATCH'])
@endpoint('agents:read', write=True)
def configured_task_video(conn, principal, repo, agent_id, task_id, section):
    from flask import request
    from .video_configuration import edit
    arguments()
    body = None
    if request.method == 'PATCH':
        engine_write(principal)
        body = json_body()
    return {'task': edit(ConfiguredTaskManager(conn, principal), identifier(agent_id), task_id, section, body,
        administrative=request.path.startswith('/api/agents/v1/admin/'))}

@api.post('/agents/<agent_id>/configured-tasks/<int:task_id>/video-resources')
@api.post('/admin/agents/<agent_id>/configured-tasks/<int:task_id>/video-resources')
@endpoint('agents:read', write=True)
def configured_task_video_resources(conn,principal,repo,agent_id,task_id):
    from flask import request
    from .rest_providers.api import service
    from .errors import EngineError
    arguments();engine_write(principal)
    command=json_body()
    if not isinstance(command,dict) or set(command)!={'language'}:raise EngineError('invalid_contract',422)
    manager=ConfiguredTaskManager(conn,principal)
    effective,agent=manager.access(identifier(agent_id),request.path.startswith('/api/agents/v1/admin/'))
    rows=manager.repository.rows(agent,task_id)
    if not rows or rows[0]['tipo']!='VIDEO_GENERAR' or (rows[0]['parametros'] or {}).get('_deleted_at'):
        raise EngineError('task_not_found',404)
    rest=service()
    candidates=[p for p in rest.listing(effective)['items'] if p['adapter']=='heygen' and p['enabled']]
    if len(candidates)!=1:raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
    return rest.video_resources(effective,candidates[0]['id'],command['language'])
