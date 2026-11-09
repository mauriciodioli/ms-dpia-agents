"""Executable schemas and REST design, marking future operations explicitly."""
from . import contracts as c
from .states import JobState
from .monitoring_contracts import response_schemas


def openapi_document():
    read = {
        '/agents': 'agents:read', '/agents/{agent_id}': 'agents:read',
        '/agents/{agent_id}/status': 'agents:read', '/agents/{agent_id}/executions': 'jobs:read',
        '/jobs': 'jobs:read', '/jobs/{job_id}': 'jobs:read',
        '/jobs/{job_id}/events': 'jobs:read', '/jobs/{job_id}/result': 'results:read',
        '/metrics': 'metrics:read', '/contracts': None, '/session': None,
        '/clients': None, '/admin/overview': None,
        '/admin/jobs/{job_id}/result': None,
    }
    paths = {}
    for path, scope in read.items():
        paths[path] = {'get': {
            'summary': 'Polling read model', 'x-required-scope': scope,
            'responses': {'200': {'description': 'Owner-scoped snapshot; unavailable consumption is null'},
                          '401': {'description': 'Authentication required'},
                          '403': {'description': 'Permission denied'},
                          '503': {'description': 'Storage unavailable; never an empty success'}},
            'parameters': [{'name': name, 'in': 'path', 'required': True, 'schema': c.UUID}
                           for name in ('agent_id', 'job_id') if '{' + name + '}' in path],
        }}
    for path in ('/clients', '/clients/{client_id}/rotate', '/clients/{client_id}/revoke'):
        paths.setdefault(path, {})['post'] = {
            'summary': 'Owner session only; X-DPIA-Action: manage-api-clients required',
            'security': [{'session': []}],
            'parameters': ([{'name': 'client_id', 'in': 'path', 'required': True, 'schema': c.UUID}]
                           if '{client_id}' in path else []),
            'responses': {'200': {'description': 'Client updated; rotation returns a token once'},
                          '201': {'description': 'Client created; token returned once'}},
        }
    paths['/clients']['post']['requestBody'] = {
        'required': True, 'content': {'application/json': {'schema': c.CLIENT_CREATE}}}
    for path, method, schema in (
        ('/agents', 'post', c.AGENT_CREATE),
        ('/agents/{agent_id}', 'patch', c.AGENT_UPDATE),
        ('/agents/{agent_id}/requests', 'post', c.REQUEST_CREATE),
        ('/agents/{agent_id}/schedules', 'post', c.SCHEDULE_REQUEST),
        ('/agents/{agent_id}/activate', 'post', c.REVISION),
        ('/agents/{agent_id}/deactivate', 'post', c.REVISION),
        ('/jobs/{job_id}/cancel', 'post', c.REVISION),
        ('/schedules/{schedule_id}/deactivate', 'post', c.REVISION),
    ):
        operation = {'x-implementation-status': 'IMPLEMENTED_PHASE_B',
                     'summary': 'Revisioned engine mutation; sessions require X-DPIA-Action: manage-agents',
                     'x-required-scope': 'agents:write' if path.startswith('/agents') and not path.endswith(('/requests', '/schedules')) else 'jobs:create',
                     'parameters': [{'name': name, 'in': 'path', 'required': True, 'schema': c.UUID}
                                    for name in ('agent_id', 'job_id', 'schedule_id') if '{' + name + '}' in path],
                     'responses': {'200': {'description': 'Updated or idempotent replay'},
                                   '201': {'description': 'Created'}, '202': {'description': 'Request accepted'},
                                   '409': {'description': 'Revision, state or idempotency conflict'}}}
        if schema:
            operation['requestBody'] = {'required': True, 'content': {'application/json': {'schema': schema}}}
        if path.endswith(('/requests', '/schedules')):
            operation['parameters'].append({'name': 'Idempotency-Key', 'in': 'header', 'required': True,
                'schema': {'type': 'string', 'minLength': 1, 'maxLength': 128}})
        paths.setdefault(path, {})[method] = operation
    paths['/agents/{agent_id}/schedules']['get'] = {
        'x-required-scope': 'jobs:read', 'parameters': [{'name': 'agent_id', 'in': 'path', 'required': True, 'schema': c.UUID}],
        'responses': {'200': {'description': 'Owner-scoped schedules'}}}
    for path in ('/session', '/clients', '/admin/overview', '/admin/jobs/{job_id}/result'):
        paths[path]['get']['security'] = [{'session': []}]
    return {
        'openapi': '3.1.0', 'info': {'title': 'DPIA Agent Engine', 'version': '1.0.0'},
        'servers': [{'url': '/api/agents/v1'}], 'security': [{'bearer': []}, {'session': []}],
        'components': {
            'securitySchemes': {'bearer': {'type': 'http', 'scheme': 'bearer'},
                                'session': {'type': 'apiKey', 'in': 'cookie', 'name': 'ms_dpia_agents_session'}},
            'schemas': {'AgentCreate': c.AGENT_CREATE, 'RequestCreate': c.REQUEST_CREATE,
                        'ClientCreate': c.CLIENT_CREATE, 'ScheduleCreate': c.SCHEDULE_CREATE,
                        'Result': c.RESULT, 'AgentUpdate': c.AGENT_UPDATE,
                        'JobState': {'enum': [state.value for state in JobState]}, **response_schemas()},
        },
        'paths': paths,
        'x-monitoring': {'transport': 'polling', 'recommended_interval_seconds': 5,
                         'future_transport': 'SSE', 'event_cursor': 'job-local sequence',
                         'worker_visibility': 'administrator session only'},
    }
