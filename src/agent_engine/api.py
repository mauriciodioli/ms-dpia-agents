"""Phase A authentication, polling read models and protected admin overview."""
from functools import wraps
from uuid import UUID
from flask import Blueprint, current_app, jsonify, request, render_template
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from utils.db import db
from .auth import authenticate, issue_client, revoke_client, rotate_client, public_client, now_utc, require_session_write
from .contracts import API_VERSION, iso
from .errors import EngineError
from .models import clients, schedules
from .repository import ReadRepository
from .states import JobState

api = Blueprint('agent_engine', __name__, url_prefix='/api/agents/v1')
admin = Blueprint('agent_engine_admin', __name__)


def engine():
    configured = current_app.extensions.get('agent_engine_engine')
    return configured if configured is not None else db.engine


def endpoint(scope=None, *, admin_only=False, write=False, html=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with (engine().begin() if write else engine().connect()) as conn:
                principal = authenticate(conn, admin_only=admin_only)
                if scope:
                    principal.require(scope)
                result = fn(conn, principal, ReadRepository(conn, principal), *args, **kwargs)
            if html:
                return result
            body, status = result if isinstance(result, tuple) else (result, 200)
            return jsonify(api_version=API_VERSION, snapshot_at=iso(now_utc()), **body), status
        return wrapped
    return decorate


@api.after_request
@admin.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Vary'] = 'Authorization, Cookie'
    if request.endpoint == 'agent_engine_admin.panel':
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response


@api.errorhandler(EngineError)
@admin.errorhandler(EngineError)
def public_error(error):
    response = jsonify(error=error.code, api_version=API_VERSION)
    if error.status == 401:
        response.headers['WWW-Authenticate'] = 'Bearer realm="ms-dpia-agents"'
    return response, error.status


@api.errorhandler(SQLAlchemyError)
@admin.errorhandler(SQLAlchemyError)
def storage_unavailable(error):
    # Never serialize exceptions: drivers may include URIs or SQL parameters.
    response = jsonify(error='engine_storage_unavailable', api_version=API_VERSION)
    response.headers['Retry-After'] = '5'
    return response, 503


def identifier(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise EngineError('invalid_identifier') from None
    return value


def arguments(allowed=()):
    if set(request.args) - set(allowed) or any(len(request.args.getlist(key)) != 1 for key in request.args):
        raise EngineError('invalid_query')


def page():
    try:
        limit = int(request.args.get('limit', '25'))
        if not 1 <= limit <= 100:
            raise ValueError
    except ValueError:
        raise EngineError('invalid_page') from None
    after = request.args.get('after')
    if after is not None:
        identifier(after)
    return limit, after


def json_body():
    if not request.is_json:
        raise EngineError('json_required', 415)
    if (request.content_length or 0) > 65536 or len(request.get_data(cache=True)) > 65536:
        raise EngineError('request_too_large', 413)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise EngineError('invalid_contract')
    return value


def engine_write(principal):
    if principal.kind == 'SESSION':
        require_session_write(principal, 'manage-agents')


@api.post('/agents')
@endpoint('agents:write', write=True)
def create_agent(conn, principal, repo):
    from .management import AgentManager
    arguments()
    engine_write(principal)
    return {'agent': AgentManager(conn, principal).save(json_body())}, 201


@api.patch('/agents/<agent_id>')
@endpoint('agents:write', write=True)
def update_agent(conn, principal, repo, agent_id):
    from .management import AgentManager
    arguments()
    engine_write(principal)
    return {'agent': AgentManager(conn, principal).save(json_body(), identifier(agent_id))}


@api.post('/agents/<agent_id>/activate')
@api.post('/agents/<agent_id>/deactivate')
@endpoint('agents:write', write=True)
def toggle_agent(conn, principal, repo, agent_id):
    from .management import AgentManager
    arguments()
    engine_write(principal)
    enabled = request.path.endswith('/activate')
    return {'agent': AgentManager(conn, principal).set_enabled(identifier(agent_id), json_body(), enabled)}


@api.post('/agents/<agent_id>/requests')
@endpoint('jobs:create', write=True)
def create_request(conn, principal, repo, agent_id):
    from .dispatcher import Dispatcher
    from .repository import public_job
    arguments()
    engine_write(principal)
    row, created = Dispatcher(conn).submit(principal, identifier(agent_id), json_body(),
                                          request.headers.get('Idempotency-Key'))
    return {'job': public_job(row), 'replayed': not created}, 202 if created else 200


@api.route('/agents/<agent_id>/schedules', methods=['GET', 'POST'])
@endpoint(write=True)
def agent_schedules(conn, principal, repo, agent_id):
    from .dispatcher import Dispatcher, public_schedule
    arguments()
    identifier(agent_id)
    if request.method == 'POST':
        principal.require('jobs:create')
        engine_write(principal)
        row, created = Dispatcher(conn).create_schedule(principal, agent_id, json_body(),
                                                       request.headers.get('Idempotency-Key'))
        return {'schedule': public_schedule(row), 'replayed': not created}, 201 if created else 200
    principal.require('jobs:read')
    repo.agent(agent_id)
    rows = conn.execute(select(schedules).where(schedules.c.owner_id == principal.owner_id,
        schedules.c.agent_id == agent_id).order_by(schedules.c.created_at.desc()).limit(100)).mappings()
    return {'items': [public_schedule(row) for row in rows], 'list_limit': 100}


@api.post('/schedules/<schedule_id>/deactivate')
@endpoint('jobs:create', write=True)
def deactivate_schedule(conn, principal, repo, schedule_id):
    from .dispatcher import Dispatcher
    arguments()
    engine_write(principal)
    return Dispatcher(conn).deactivate_schedule(principal, identifier(schedule_id), json_body())


@api.post('/jobs/<job_id>/cancel')
@endpoint('jobs:create', write=True)
def cancel_job(conn, principal, repo, job_id):
    from .dispatcher import Dispatcher
    from .repository import public_job
    arguments()
    engine_write(principal)
    return {'job': public_job(Dispatcher(conn).cancel(principal, identifier(job_id), json_body()))}


@api.get('/agents')
@endpoint('agents:read')
def list_agents(conn, principal, repo):
    arguments({'limit', 'after'})
    return repo.agents(*page())


@api.get('/agents/<agent_id>')
@endpoint('agents:read')
def get_agent(conn, principal, repo, agent_id):
    arguments()
    return {'agent': repo.public_agent(repo.agent(identifier(agent_id)), configuration=True)}


@api.get('/agents/<agent_id>/status')
@endpoint('agents:read')
def agent_status(conn, principal, repo, agent_id):
    arguments()
    return {'agent': repo.public_agent(repo.agent(identifier(agent_id)))}


@api.get('/jobs')
@endpoint('jobs:read')
def list_jobs(conn, principal, repo):
    arguments({'limit', 'after', 'agent_id', 'state'})
    agent_id = request.args.get('agent_id')
    state = request.args.get('state')
    if agent_id:
        identifier(agent_id)
    if state and state not in JobState._value2member_map_:
        raise EngineError('invalid_state')
    return repo.jobs(*page(), agent_id=agent_id, state=state)


@api.get('/agents/<agent_id>/executions')
@endpoint('jobs:read')
def execution_history(conn, principal, repo, agent_id):
    arguments({'limit', 'after'})
    return repo.jobs(*page(), agent_id=identifier(agent_id))


@api.get('/jobs/<job_id>')
@endpoint('jobs:read')
def get_job(conn, principal, repo, job_id):
    from .repository import public_job
    arguments()
    return {'job': public_job(repo.job(identifier(job_id)))}


@api.get('/jobs/<job_id>/result')
@endpoint('results:read')
def get_result(conn, principal, repo, job_id):
    arguments()
    return repo.result(identifier(job_id))


@api.get('/jobs/<job_id>/events')
@endpoint('jobs:read')
def job_events(conn, principal, repo, job_id):
    arguments({'after_sequence', 'limit'})
    limit, _ = page()
    try:
        after = int(request.args.get('after_sequence', '0'))
        if after < 0:
            raise ValueError
    except ValueError:
        raise EngineError('invalid_event_cursor') from None
    return repo.events(identifier(job_id), after, limit)


@api.get('/metrics')
@endpoint('metrics:read')
def metrics(conn, principal, repo):
    arguments()
    return repo.metrics()


@api.route('/clients', methods=['GET', 'POST'])
@endpoint(write=True)
def api_clients(conn, principal, repo):
    if principal.kind != 'SESSION':
        raise EngineError('session_required', 403)
    arguments()
    if request.method == 'POST':
        return issue_client(conn, principal, json_body()), 201
    rows = conn.execute(select(clients).where(clients.c.owner_id == principal.owner_id)
                        .order_by(clients.c.created_at.desc()).limit(100)).mappings()
    return {'items': [public_client(row) for row in rows], 'list_limit': 100}


@api.post('/clients/<client_id>/revoke')
@endpoint(write=True)
def revoke(conn, principal, repo, client_id):
    arguments()
    return revoke_client(conn, principal, identifier(client_id))


@api.post('/clients/<client_id>/rotate')
@endpoint(write=True)
def rotate(conn, principal, repo, client_id):
    arguments()
    return rotate_client(conn, principal, identifier(client_id))


@api.get('/admin/overview')
@endpoint(admin_only=True)
def admin_overview(conn, principal, repo):
    arguments()
    return repo.admin_overview()


@admin.get('/admin/agents')
@endpoint(admin_only=True, html=True)
def panel(conn, principal, repo):
    return render_template('agent_engine_admin.html')


@api.get('/admin/jobs/<job_id>/result')
@endpoint(admin_only=True)
def admin_result(conn, principal, repo, job_id):
    arguments()
    return repo.admin_result(identifier(job_id))


@api.get('/contracts')
@endpoint()
def contracts(conn, principal, repo):
    from .specification import openapi_document
    return {'openapi': openapi_document()}
