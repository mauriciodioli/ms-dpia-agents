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


def edit(manager, agent_id, task_id, section, body=None, administrative=False):
    from .auth import now_utc
    from .management import audit_agent
    principal, agent = manager.access(agent_id, administrative)
    rows = manager.repository.rows(agent, task_id)
    if (not rows or rows[0]['tipo'] != 'VIDEO_GENERAR'
            or (rows[0]['parametros'] or {}).get('_deleted_at')):
        raise EngineError('task_not_found', 404)
    row = rows[0]
    params = deepcopy(row['parametros'] or {})
    revision = params.get('_configuration_revision', 1)
    video = configuration(params)
    if section not in (*FIELDS, 'settings'):
        raise EngineError('invalid_video_configuration', 422)
    if body is not None:
        principal.require('agents:write')
        values = validate_editor(body) if section == 'settings' else preferences(section, body)
        if body['expected_revision'] != revision:
            raise EngineError('revision_conflict', 409)
        if section == 'settings':
            video['editor'] = values
            video['script']['custom_script'] = values['script'] if values['script_mode']=='custom' else ''
            video['production'].update(video_type=KINDS[values['kind']], duration_seconds=values['duration_seconds'],
                language=values['language'], format=values['aspect_ratio'],
                avatar_id='' if values['avatar']=='auto' else values['avatar'],
                voice_id='' if values['voice']=='auto' else values['voice'],
                budget_credits=int(values['max_cost']), automatic_production=values['approval']=='automatic')
        else:
            video[section] = values
            video.pop('editor', None)  # B2B section edits take precedence over a previous editor snapshot.
        params['video'] = video
        params['_configuration_revision'] = revision + 1
        manager.repository.save(row, name=values['name'].strip() if section=='settings' else row['nombre'], parameters=params, now=now_utc())
        revision += 1
        audit_agent(manager.conn, principal, agent, 'TASK_VIDEO_CONFIGURATION_UPDATED',
                    {'task_id': task_id, 'section': section, 'task_revision': revision})
    if body is not None and section=='settings':row={**row,'nombre':values['name'].strip()}
    return {'settings':editor_values(row,video), 'id': task_id, 'revision': revision, 'video_configuration': video,
            'execution_available': False}


KINDS = {'news':'Noticiero','explanatory':'Explicativo','promotional':'Promocional','summary':'Resumen'}


def editor_values(row, video):
    production, script = video['production'], video['script']
    return {**{'name':row['nombre'], 'objective':'',
        'kind':next((k for k,v in KINDS.items() if v==production['video_type']),'news'),
        'duration_seconds':production['duration_seconds'], 'language':production['language'],
        'aspect_ratio':production['format'], 'tone':'professional',
        'avatar':production['avatar_id'] or 'auto', 'voice':production['voice_id'] or 'auto',
        'script_mode':'custom' if script['custom_script'] else 'automatic',
        'script':script['custom_script'], 'content_source':'agent', 'schedule':'manual',
        'time':((row.get('parametros') or {}).get('schedule') or {}).get('time','00:00'), 'timezone':((row.get('parametros') or {}).get('schedule') or {}).get('timezone','UTC'), 'approval':'automatic' if production['automatic_production'] else 'manual',
        'max_cost':str(production['budget_credits'])}, **{k:v for k,v in video.get('editor',{}).items() if k in ('objective','tone','content_source','schedule','time','timezone')},
        'name':row['nombre']}


def validate_editor(body):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    import re
    required={'name','objective','kind','duration_seconds','language','aspect_ratio','tone','avatar',
              'voice','script_mode','script','content_source','schedule','time','timezone','approval','max_cost'}
    if not isinstance(body,dict) or set(body)!=required|{'expected_revision'}:
        raise EngineError('invalid_video_configuration',422)
    if type(body['expected_revision']) is not int or body['expected_revision']<1:
        raise EngineError('invalid_video_configuration',422)
    limits={'name':120,'objective':4000,'language':20,'avatar':160,'voice':160,'script':20000,'timezone':64,'max_cost':7,'time':5}
    for key,limit in limits.items():
        if not isinstance(body[key],str) or len(body[key])>limit:
            raise EngineError('invalid_video_configuration',422)
    enums={'kind':KINDS,'aspect_ratio':('16:9','9:16','1:1'),
           'tone':('professional','friendly','informative','enthusiastic'),
           'script_mode':('automatic','custom'),'content_source':('agent','user'),
           'schedule':('manual',),'approval':('manual','automatic')}
    for key,values in enums.items():
        if not isinstance(body[key],str) or body[key] not in values:raise EngineError('invalid_video_configuration',422)
    if (not body['name'].strip() or not body['objective'].strip() or not body['language'].strip()
            or type(body['duration_seconds']) is not int or not 1<=body['duration_seconds']<=3600
            or not re.fullmatch(r'(0|[1-9][0-9]{0,6})',body['max_cost']) or int(body['max_cost'])>1000000
            or not re.fullmatch(r'([01][0-9]|2[0-3]):[0-5][0-9]',body['time'])
            or (body['script_mode']=='custom' and not body['script'].strip())):
        raise EngineError('invalid_video_configuration',422)
    try:ZoneInfo(body['timezone'])
    except (ValueError,ZoneInfoNotFoundError):raise EngineError('invalid_video_configuration',422) from None
    return {key:body[key] for key in required}
