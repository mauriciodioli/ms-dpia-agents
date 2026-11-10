"""First-party developer portal, isolated from execution processes."""
from flask import Blueprint, jsonify, render_template
from sqlalchemy.exc import SQLAlchemyError
from .api import engine, endpoint, arguments
from .errors import EngineError
from .contracts import API_VERSION, iso
from .auth import now_utc

portal = Blueprint('agent_developer_portal', __name__)

@portal.get('/developers')
def developers_page():
    # Page is only a shell. Every API action checks authenticated session.
    return render_template('agents_developers.html')

@portal.get('/api/agents/v1/client-connection')
@endpoint()
def client_connection(conn, principal, repo):
    arguments()
    return {'connection': {'authenticated': True, 'kind': principal.kind,
                           'scopes': sorted(principal.scopes),
                           'all_agents': principal.all_agents,
                           'agent_ids': sorted(principal.agent_ids)}}
