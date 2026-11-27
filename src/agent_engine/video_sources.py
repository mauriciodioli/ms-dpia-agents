"""Owner-scoped, persisted source material for an existing video child task."""
import json
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import MetaData, Table, inspect, select
from markupsafe import Markup
from . import models as m
from .configured_task_repository import ConfiguredTaskRepository
from .errors import EngineError
from .video_configuration import configuration


def publication_context(conn, owner, source):
    if (not isinstance(source, dict) or set(source) != {'type', 'application', 'publication_id'}
            or source['type'] != 'publication' or source['application'] != 'bot421'
            or type(source['publication_id']) is not int or source['publication_id'] < 1):
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    metadata = MetaData()
    publication = Table('publicacion', metadata, autoload_with=conn, resolve_fks=False)
    row = conn.execute(select(publication).where(
        publication.c.id == source['publication_id'], publication.c.user_id == owner
    )).mappings().first()
    if not row:
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    extra = {}
    if inspect(conn).has_table('publicacion_contenido_extra'):
        table = Table('publicacion_contenido_extra', metadata, autoload_with=conn, resolve_fks=False)
        extra = conn.execute(select(table).where(
            table.c.publicacion_id == row['id'], table.c.user_id == owner
        )).mappings().first() or {}
    clean = lambda value, limit: Markup(str(value or '')).striptags()[:limit]
    content = {key: clean(row.get(key), 1400) for key in ('titulo', 'texto', 'descripcion', 'idioma')}
    content.update({key: clean(extra.get(key), 900) for key in ('noticias', 'ofertas')})
    return content


def source_context(conn, job):
    agent = conn.execute(select(m.agents).where(m.agents.c.id == job['agent_id'],
        m.agents.c.owner_id == job['owner_id']).with_for_update()).mappings().first()
    if not agent or not job.get('legacy_task_id'):
        raise EngineError('VIDEO_TASK_NOT_AUTHORIZED', 403)
    repo = ConfiguredTaskRepository(conn)
    children = repo.rows(agent, job['legacy_task_id'])
    if not children or children[0]['tipo'] != 'VIDEO_GENERAR':
        raise EngineError('VIDEO_TASK_NOT_AUTHORIZED', 403)
    child = children[0]
    params = child['parametros'] or {}
    if params.get('_deleted_at'):
        raise EngineError('VIDEO_TASK_NOT_AUTHORIZED', 403)
    video = configuration(params)
    if 'source' in params and not params.get('parent_task_id') and not video.get('parent_task_id'):
        content = publication_context(conn, job['owner_id'], params['source'])
        execution = params.get('_publication_execution') or {}
        key = execution.get('key')
        schedule = str(uuid5(NAMESPACE_URL, f"immediate-task:{job['owner_id']}:{key}")) if key else None
        commercial = execution.get('commercial') if schedule and schedule == job.get('schedule_id') else None
        return {'task_id': child['id'], 'parent_task_id': None, 'commercial': commercial,
                'configuration_revision': params.get('_configuration_revision', 1),
                'name': content['titulo'] or child['nombre'], 'video': video,
                'results': [], 'publication': content}
    parent_id = video.get('parent_task_id', params.get('parent_task_id'))
    if type(parent_id) is not int or parent_id == child['id']:
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    if params.get('parent_task_id', parent_id) != parent_id:
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    parents = repo.rows(agent, parent_id)
    if not parents or parents[0]['tipo'] == 'VIDEO_GENERAR' or (parents[0]['parametros'] or {}).get('_deleted_at'):
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    context = {'task_id': child['id'], 'parent_task_id': parent_id,
               'configuration_revision': params.get('_configuration_revision', 1),
               'name': child['nombre'], 'video': video, 'results': []}
    if parents[0]['tipo'] == 'PUBLICACION':
        source = (parents[0]['parametros'] or {}).get('source')
        content = publication_context(conn, job['owner_id'], source)
        context['publication'] = content
        if content['titulo']:
            context['name'] = content['titulo']
        return context

    # Explicitly choose the latest persisted parent investigation. No provider calls,
    # no raw worker drafts, and no other agent's or owner's history.
    query = select(m.results.c.id, m.results.c.job_id, m.results.c.payload).join(m.jobs,
        (m.results.c.job_id == m.jobs.c.id) & (m.results.c.owner_id == m.jobs.c.owner_id)).where(
            m.jobs.c.owner_id == job['owner_id'], m.jobs.c.agent_id == job['agent_id'],
            m.jobs.c.legacy_task_id == parent_id, m.jobs.c.state.in_(['REVIEWING', 'DELIVERED'])
        ).order_by(m.jobs.c.created_at.desc(), m.jobs.c.id.desc(), m.results.c.version.desc()).limit(1)
    result = conn.execute(query).mappings().first()
    if result:
        context['results'].append(dict(result))
    return context


def evidence(context):
    """Reject empty/unreferenced search material rather than manufacture content."""
    outputs = []
    for result in context['results']:
        payload = result['payload']
        if not isinstance(payload, dict):
            continue
        items = payload.get('items') or []
        findings = payload.get('findings') or []
        sources = payload.get('sources') or []
        useful_items = [item for item in items if isinstance(item, dict)
            and all(isinstance(item.get(key), str) and item[key].strip() for key in ('title', 'description', 'url'))]
        useful_findings = [item for item in findings if isinstance(item, dict)
            and isinstance(item.get('text'), str) and item['text'].strip() and item.get('source_ids')
            and set(item['source_ids']).issubset({s.get('id') for s in sources if isinstance(s, dict)})]
        if useful_items or useful_findings:
            outputs.append(result)
    if not outputs:
        raise EngineError('VIDEO_SCRIPT_SOURCE_INSUFFICIENT', 422)
    try:
        encoded = json.dumps(outputs, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise EngineError('invalid_evidence_json', 500) from None
    if len(encoded.encode('utf-8')) > 100000:
        raise EngineError('VIDEO_SCRIPT_SOURCE_LIMIT', 422)
    return outputs
