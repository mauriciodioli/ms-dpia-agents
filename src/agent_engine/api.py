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
            if status == 204:return '',204
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


@api.get('/jobs/<job_id>/review')
@endpoint('jobs:read')
def inspect_job_review(conn, principal, repo, job_id):
    """Owner-only review preview; does not make results publicly deliverable."""
    from .review_coordinator import ReviewCoordinator
    from . import models as m
    arguments()
    if principal.kind != 'SESSION':
        raise EngineError('reviewer_session_required', 403)
    job_id = identifier(job_id)
    repo.job(job_id)  # tenant boundary
    report = ReviewCoordinator(conn).inspect(owner_id=principal.owner_id, job_id=job_id)
    result_row = conn.execute(select(m.results.c.payload).where(
        m.results.c.owner_id == principal.owner_id,
        m.results.c.id == report['result_id'],
        m.results.c.job_id == job_id)).scalar_one()
    return {'review': report, 'result': result_row}


@api.post('/jobs/<job_id>/review')
@endpoint('jobs:create', write=True)
def decide_job_review(conn, principal, repo, job_id):
    """Explicit session decision, never an automatic evidence approval."""
    from .review_coordinator import ReviewCoordinator
    arguments()
    engine_write(principal)
    if principal.kind != 'SESSION':
        raise EngineError('reviewer_session_required', 403)
    job_id = identifier(job_id)
    repo.job(job_id)
    body = json_body()
    if set(body) != {'decision', 'reason_codes', 'expected_revision'}:
        raise EngineError('invalid_contract')
    report = ReviewCoordinator(conn).inspect(owner_id=principal.owner_id, job_id=job_id)
    if type(body['expected_revision']) is not int or body['expected_revision'] != report['revision']:
        raise EngineError('revision_conflict', 409)
    decision = ReviewCoordinator(conn).decide(
        owner_id=principal.owner_id, job_id=job_id, actor_id=principal.actor_id,
        decision=body['decision'], reason_codes=body['reason_codes'])
    return {'review_decision': decision}


@api.get('/jobs/<job_id>/review-history')
@endpoint('jobs:read')
def job_review_history(conn, principal, repo, job_id):
    """Owner-only previous result versions and review decisions."""
    from . import models as m
    arguments()
    if principal.kind != 'SESSION':
        raise EngineError('reviewer_session_required', 403)
    job_id = identifier(job_id)
    job = repo.job(job_id)
    results = conn.execute(select(m.results).where(m.results.c.owner_id == principal.owner_id,
        m.results.c.job_id == job_id).order_by(m.results.c.version)).mappings().all()
    reviews = conn.execute(select(m.reviews).where(m.reviews.c.owner_id == principal.owner_id,
        m.reviews.c.job_id == job_id).order_by(m.reviews.c.cycle)).mappings().all()
    return {'state': job['state'], 'revision': job['revision'],
        'correction_count': job['correction_count'],
        'max_corrections': job['request_snapshot'].get('limits', {}).get('max_corrections', 0),
        'results': [{'id': r['id'], 'version': r['version'], 'payload': r['payload'],
                     'evidence_status': r['evidence_status']} for r in results],
        'reviews': [{'result_id': r['result_id'], 'cycle': r['cycle'],
                     'decision': r['decision'], 'reason_codes': r['reason_codes']} for r in reviews]}


@api.post('/jobs/<job_id>/retry-correction')
@endpoint('jobs:create', write=True)
def retry_job_correction(conn, principal, repo, job_id):
    """Explicit owner action. Local demo only; no provider replay."""
    from .corrections import retry_local_correction
    arguments()
    engine_write(principal)
    if principal.kind != 'SESSION':
        raise EngineError('reviewer_session_required', 403)
    job_id = identifier(job_id)
    repo.job(job_id)
    body = json_body()
    if set(body) != {'expected_revision'} or type(body['expected_revision']) is not int:
        raise EngineError('invalid_contract')
    return {'retry': retry_local_correction(conn, owner_id=principal.owner_id,
        job_id=job_id, actor_id=principal.actor_id,
        expected_revision=body['expected_revision'])}


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
    return render_template('agents_workspace.html')


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


@api.get('/session')
@endpoint()
def workspace_session(conn, principal, repo):
    """Minimal live permissions and tool contracts for the first-party workspace."""
    from .tools import default_registry
    arguments()
    if principal.kind != 'SESSION':
        raise EngineError('session_required', 403)
    return {'session': {'admin': principal.admin, 'scopes': sorted(principal.scopes)},
            'tools': [{'id': tool.id, 'provider': tool.provider,
                       'input_schema': tool.input_schema,
                       'implementation_status': tool.implementation_status}
                      for tool in default_registry().tools.values()],
            'availability': {'execution': False, 'integrations_management': principal.admin,
                             'users_management': False}}


@api.get('/inbox/<inbox_id>')
@endpoint('jobs:read')
def inbox_status(conn, principal, repo, inbox_id):
    """Read status of a DB-submitted request without exposing its payload."""
    from .inbox import inbox
    arguments()
    row = conn.execute(select(inbox).where(
        inbox.c.id == identifier(inbox_id),
        inbox.c.owner_id == principal.owner_id)).mappings().first()
    if row is None or (principal.kind == 'API_CLIENT' and row['client_id'] != principal.actor_id):
        raise EngineError('inbox_request_not_found', 404)
    return {'inbox': {'id': row['id'], 'state': row['state'],
        'job_id': row['job_id'], 'error_code': row['error_code'],
        'created_at': iso(row['created_at']),
        'processed_at': iso(row['processed_at']) if row['processed_at'] else None}}
