"""Versioned, provider-independent contracts; no tool execution in Phase A."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from jsonschema import Draft202012Validator, FormatChecker
from .errors import EngineError

API_VERSION = 'agents.v1'
SCOPES = frozenset({'agents:read', 'agents:write', 'agents:delete', 'jobs:create', 'jobs:read',
                    'results:read', 'metrics:read','mcp:read','mcp:write','mcp:execute','mcp:approve'})
UUID = {'type': 'string', 'format': 'uuid'}
TOOL_ID = {'type': 'string', 'pattern': r'^[a-z][a-z0-9_.-]{2,79}$'}
LIMITS = {
    'type': 'object', 'additionalProperties': False,
    'required': ['max_tool_calls', 'max_output_tokens', 'max_duration_seconds', 'max_corrections'],
    'properties': {
        'max_tool_calls': {'type': 'integer', 'minimum': 1, 'maximum': 20},
        'max_output_tokens': {'type': 'integer', 'minimum': 1, 'maximum': 16000},
        'max_duration_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600},
        'max_corrections': {'type': 'integer', 'minimum': 0, 'maximum': 2},
    },
}
AGENT_CREATE = {
    '$id': 'urn:dpia:agents:v1:agent-create', 'type': 'object', 'additionalProperties': False,
    'required': ['name', 'instructions', 'capabilities', 'timezone', 'limits'],
    'properties': {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 120},
        'description': {'type': 'string', 'maxLength': 1000},
        'instructions': {'type': 'string', 'minLength': 1, 'maxLength': 8000},
        'timezone': {'type': 'string', 'minLength': 1, 'maxLength': 64},
        'capabilities': {'type': 'array', 'minItems': 1, 'maxItems': 16, 'uniqueItems': True, 'items': TOOL_ID},
        'limits': LIMITS,
        'tool_parameters': {'type': 'object', 'maxProperties': 16,
                            'propertyNames': TOOL_ID, 'additionalProperties': {'type': 'object'}},
    },
}
AGENT_UPDATE = {**AGENT_CREATE, '$id': 'urn:dpia:agents:v1:agent-update',
                'required': AGENT_CREATE['required'] + ['expected_revision'],
                'properties': {**AGENT_CREATE['properties'],
                               'expected_revision': {'type': 'integer', 'minimum': 1}}}
CLIENT_CREATE = {
    '$id': 'urn:dpia:agents:v1:client-create', 'type': 'object', 'additionalProperties': False,
    'required': ['name', 'scopes', 'all_agents', 'agent_ids', 'expires_at'],
    'properties': {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 120},
        'scopes': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                   'items': {'enum': sorted(SCOPES)}},
        'all_agents': {'type': 'boolean'},
        'agent_ids': {'type': 'array', 'maxItems': 1000, 'uniqueItems': True, 'items': UUID},
        'expires_at': {'type': 'string', 'format': 'date-time'},
    },
}
REQUEST_CREATE = {
    '$id': 'urn:dpia:agents:v1:request-create', 'type': 'object', 'additionalProperties': False,
    'required': ['limits'], 'anyOf': [{'required':['pipeline','instructions']}, {'required':['objective']}],
    'properties': {
        'instructions': {'type': 'string', 'maxLength': 8000},
        'objective': {'type':'string','minLength':1,'maxLength':4000},
        'pipeline': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['tool', 'parameters'],
            'properties': {'tool': TOOL_ID, 'parameters': {'type': 'object'}},
        }},
        'execute_at': {'type': 'string', 'format': 'date-time'},
        'deliver_not_before': {'type': 'string', 'format': 'date-time'},
        'deadline_at': {'type': 'string', 'format': 'date-time'},
        'priority': {'type': 'integer', 'minimum': 0, 'maximum': 9},
        'limits': LIMITS,
    },
}
SCHEDULE_CREATE = {
    '$id': 'urn:dpia:agents:v1:schedule', 'type': 'object', 'additionalProperties': False,
    'required': ['timezone', 'frequency', 'weekdays', 'execution_time', 'delivery_time', 'dst_policy'],
    'properties': {
        'timezone': {'type': 'string', 'minLength': 1, 'maxLength': 64},
        'frequency': {'enum': ['DAILY', 'WEEKLY']},
        'weekdays': {'type': 'array', 'minItems': 1, 'maxItems': 7, 'uniqueItems': True,
                     'items': {'type': 'integer', 'minimum': 1, 'maximum': 7}},
        'execution_time': {'type': 'string', 'pattern': r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$'},
        'delivery_time': {'type': 'string', 'pattern': r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$'},
        'dst_policy': {'const': 'REJECT_AMBIGUOUS_OR_NONEXISTENT'},
    },
}
REVISION = {'type': 'object', 'additionalProperties': False, 'required': ['expected_revision'],
            'properties': {'expected_revision': {'type': 'integer', 'minimum': 1}}}
SCHEDULE_REQUEST = {**SCHEDULE_CREATE, '$id': 'urn:dpia:agents:v1:schedule-request',
                    'required': SCHEDULE_CREATE['required'] + ['request'],
                    'properties': {**SCHEDULE_CREATE['properties'], 'request': REQUEST_CREATE}}

RESULT = {
    '$id': 'urn:dpia:agents:v1:result', 'type': 'object', 'additionalProperties': False,
    'required': ['schema_version', 'summary', 'findings', 'sources', 'warnings'],
    'properties': {
        'schema_version': {'const': 'agents.result.v1'},
        'summary': {'type': 'string', 'maxLength': 20000},
        'findings': {'type': 'array', 'maxItems': 100, 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['text', 'source_ids'],
            'properties': {'text': {'type': 'string', 'maxLength': 8000},
                           'source_ids': {'type': 'array', 'uniqueItems': True,
                                          'items': {'type': 'string', 'maxLength': 120}}}}},
        'sources': {'type': 'array', 'maxItems': 100, 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['id', 'url', 'title', 'retrieved_at'],
            'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 120},
                           'url': {'type': 'string', 'maxLength': 2000, 'format': 'uri'},
                           'title': {'type': 'string', 'maxLength': 1000},
                           'retrieved_at': {'type': 'string', 'format': 'date-time'}}}},
        'warnings': {'type': 'array', 'maxItems': 100, 'items': {'type': 'string', 'maxLength': 2000}},
    },
}


def validate(schema: dict, value: dict) -> dict:
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value):
        raise EngineError('invalid_contract')
    for field in ('name', 'instructions'):
        if field in value and schema in (AGENT_CREATE, AGENT_UPDATE) and not value[field].strip():
            raise EngineError('invalid_contract')
    if 'timezone' in value:
        try:
            ZoneInfo(value['timezone'])
        except (ValueError, ZoneInfoNotFoundError):
            raise EngineError('invalid_timezone') from None
    if schema is CLIENT_CREATE:
        if value['all_agents'] and value['agent_ids']:
            raise EngineError('ambiguous_agent_grant')
    if schema is REQUEST_CREATE:
        dates = {key: utc(value[key]) for key in ('execute_at', 'deadline_at', 'deliver_not_before') if key in value}
        if 'execute_at' in dates and 'deadline_at' in dates and dates['deadline_at'] <= dates['execute_at']:
            raise EngineError('invalid_deadline')
    if schema is RESULT:
        from urllib.parse import urlsplit, parse_qs
        ids = [source['id'] for source in value['sources']]
        if len(ids) != len(set(ids)) or any(set(finding['source_ids']) - set(ids) for finding in value['findings']):
            raise EngineError('invalid_source_reference')
        for source in value['sources']:
            try:
                url = urlsplit(source['url'])
                if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
                        or any(key.lower() in {'token', 'api_key', 'access_token', 'password', 'secret'}
                               for key in parse_qs(url.query))):
                    raise ValueError
            except ValueError:
                raise EngineError('invalid_source_url') from None
    return value


def utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, AttributeError):
        raise EngineError('timezone_offset_required') from None


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec='microseconds') + 'Z'
