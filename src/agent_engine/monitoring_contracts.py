"""Polling response schemas; the same snapshots can be carried by future SSE."""
from .contracts import UUID
from .states import JobState

DATE = {'type': 'string', 'format': 'date-time'}
NULLABLE_DATE = {'type': ['string', 'null'], 'format': 'date-time'}
NULLABLE_COUNT = {'type': ['integer', 'null'], 'minimum': 0}

AGENT_SNAPSHOT = {
    'type': 'object', 'additionalProperties': False,
    'required': ['id', 'name', 'description', 'configuration_state', 'activity_state',
                 'revision', 'timezone', 'created_at', 'updated_at'],
    'properties': {
        'id': UUID, 'name': {'type': 'string'}, 'description': {'type': 'string'},
        'configuration_state': {'enum': ['ENABLED', 'DISABLED']},
        'activity_state': {'enum': ['IDLE', 'WAITING', 'WORKING']},
        'revision': {'type': 'integer', 'minimum': 1}, 'timezone': {'type': 'string'},
        'created_at': DATE, 'updated_at': DATE,
        'instructions': {'type': 'string'}, 'limits': {'type': 'object'},
        'search_parameters': {'type': 'object'},
        'capabilities': {'type': 'array', 'items': {'type': 'string'}},
    },
}
JOB_SNAPSHOT = {
    'type': 'object', 'additionalProperties': False,
    'required': ['id', 'agent_id', 'state', 'revision', 'progress', 'priority',
                 'correlation_id', 'error_code', 'created_at', 'updated_at', 'execute_at',
                 'deliver_not_before', 'deadline_at', 'started_at', 'finished_at'],
    'properties': {
        'id': UUID, 'agent_id': UUID, 'correlation_id': UUID,
        'state': {'enum': [state.value for state in JobState]},
        'revision': {'type': 'integer', 'minimum': 1},
        'progress': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 100},
        'priority': {'type': 'integer', 'minimum': 0, 'maximum': 9},
        'error_code': {'type': ['string', 'null']},
        'created_at': DATE, 'updated_at': DATE,
        **{key: NULLABLE_DATE for key in ('execute_at', 'deliver_not_before', 'deadline_at', 'started_at', 'finished_at')},
    },
}
WORKER_SNAPSHOT = {
    'type': 'object', 'additionalProperties': False,
    'required': ['id', 'capabilities', 'availability', 'heartbeat_at'],
    'properties': {'id': {'type': 'string'}, 'capabilities': {'type': 'array', 'items': {'type': 'string'}},
                   'availability': {'enum': ['AVAILABLE', 'BUSY', 'DISCONNECTED']},
                   'heartbeat_at': NULLABLE_DATE},
}
PROVIDER_USAGE = {
    'type': 'object', 'additionalProperties': False,
    'required': ['provider_id', 'currency', 'calls', 'input_tokens', 'output_tokens', 'cost'],
    'properties': {'provider_id': {'type': 'string'}, 'currency': {'type': ['string', 'null']},
                   'calls': NULLABLE_COUNT, 'input_tokens': NULLABLE_COUNT, 'output_tokens': NULLABLE_COUNT,
                   'cost': {'type': ['string', 'null'], 'pattern': r'^\d+(?:\.\d+)?$'}},
}
METRICS_SNAPSHOT = {
    'type': 'object', 'required': ['jobs_by_state', 'usage_status', 'provider_usage'],
    'properties': {'jobs_by_state': {'type': 'object', 'propertyNames': {'enum': [state.value for state in JobState]},
                                    'additionalProperties': {'type': 'integer', 'minimum': 0}},
                   'usage_status': {'enum': ['MEASURED', 'UNAVAILABLE']},
                   'provider_usage': {'type': 'array', 'items': PROVIDER_USAGE}},
}
EVENT_SNAPSHOT = {
    'type': 'object', 'additionalProperties': False,
    'required': ['sequence', 'type', 'reason_code', 'correlation_id', 'created_at'],
    'properties': {'sequence': {'type': 'integer', 'minimum': 1}, 'type': {'type': 'string'},
                   'reason_code': {'type': ['string', 'null']}, 'correlation_id': UUID, 'created_at': DATE},
}


def response_schemas():
    return {'AgentSnapshot': AGENT_SNAPSHOT, 'JobSnapshot': JOB_SNAPSHOT,
            'WorkerSnapshot': WORKER_SNAPSHOT, 'MetricsSnapshot': METRICS_SNAPSHOT,
            'ProviderUsage': PROVIDER_USAGE, 'EventSnapshot': EVENT_SNAPSHOT,
            'APIError': {'type': 'object', 'additionalProperties': False,
                         'required': ['error', 'api_version'],
                         'properties': {'error': {'type': 'string'}, 'api_version': {'const': 'agents.v1'}}}}
