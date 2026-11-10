"""First-party developer portal, isolated from execution processes."""
from flask import Blueprint, render_template, make_response
from .api import endpoint, arguments

portal = Blueprint('agent_developer_portal', __name__)

@portal.get('/developers')
def developers_page():
    # Page is only a shell. Every API action checks authenticated session.
    response = make_response(render_template('agents_developers.html'))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response

@portal.get('/api/agents/v1/client-connection')
@endpoint()
def client_connection(conn, principal, repo):
    arguments()
    return {'connection': {'authenticated': True, 'kind': principal.kind,
                           'scopes': sorted(principal.scopes),
                           'all_agents': principal.all_agents,
                           'agent_ids': sorted(principal.agent_ids)}}
