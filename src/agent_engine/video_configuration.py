"""B2B-compatible video preferences; no provider calls or implicit authorization."""
from copy import deepcopy
from .errors import EngineError

FIELDS = {
    'script': {'instructions': 5000, 'custom_script': 20000},
    'production': {'video_type': 80, 'language': 20, 'format': 20,
                   'provider': 80, 'avatar_id': 160, 'voice_id': 160},
}


def preferences(section, payload):
    if section not in FIELDS or not isinstance(payload, dict):
        raise EngineError('invalid_video_configuration', 422)
    allowed = set(FIELDS[section]) | {'expected_revision'}
    if section == 'production':
        allowed |= {'duration_seconds', 'budget_credits', 'automatic_production'}
    if (set(payload) - allowed or type(payload.get('expected_revision')) is not int
            or payload['expected_revision'] < 1):
        raise EngineError('invalid_video_configuration', 422)
    result = {}
    for field, limit in FIELDS[section].items():
        value = payload.get(field, '')
        if not isinstance(value, str) or len(value) > limit:
            raise EngineError('invalid_video_configuration', 422)
        result[field] = value
    if section == 'production':
        duration, budget, automatic = (payload.get('duration_seconds', 60),
                                     payload.get('budget_credits', 0),
                                     payload.get('automatic_production', False))
        if (type(duration) is not int or not 1 <= duration <= 3600
                or type(budget) is not int or not 0 <= budget <= 1000000
                or type(automatic) is not bool):
            raise EngineError('invalid_video_configuration', 422)
        result.update(duration_seconds=duration, budget_credits=budget, automatic_production=automatic)
    return result


def configuration(parameters):
    """Read legacy and current B2B shapes without replacing user preferences."""
    video = deepcopy(parameters.get('video') or {})
    duration = video.get('duration_seconds', 60)
    defaults = {
        'script': {'instructions': '', 'custom_script': ''},
        'production': {'video_type': 'Noticiero', 'duration_seconds': duration,
                       'language': parameters.get('language') or
                           (parameters.get('query_context') or {}).get('language') or 'es',
                       'format': '16:9', 'provider': 'heygen', 'avatar_id': '',
                       'voice_id': '', 'budget_credits': 0, 'automatic_production': False},
    }
    for section, values in defaults.items():
        video[section] = {**values, **video.get(section, {})}
    return video


def edit(manager, agent_id, task_id, section, body=None):
    from .auth import now_utc
    from .management import audit_agent
    principal, agent = manager.access(agent_id)
    rows = manager.repository.rows(agent, task_id)
    if (not rows or rows[0]['tipo'] != 'VIDEO_GENERAR'
            or (rows[0]['parametros'] or {}).get('_deleted_at')):
        raise EngineError('task_not_found', 404)
    row = rows[0]
    params = deepcopy(row['parametros'] or {})
    revision = params.get('_configuration_revision', 1)
    video = configuration(params)
    if section not in FIELDS:
        raise EngineError('invalid_video_configuration', 422)
    if body is not None:
        principal.require('agents:write')
        values = preferences(section, body)
        if body['expected_revision'] != revision:
            raise EngineError('revision_conflict', 409)
        video[section] = values
        params['video'] = video
        params['_configuration_revision'] = revision + 1
        manager.repository.save(row, name=row['nombre'], parameters=params, now=now_utc())
        revision += 1
        audit_agent(manager.conn, principal, agent, 'TASK_VIDEO_CONFIGURATION_UPDATED',
                    {'task_id': task_id, 'section': section, 'task_revision': revision})
    return {'id': task_id, 'revision': revision, 'video_configuration': video,
            'execution_available': False}
