"""Owner-scoped, persisted source material for an existing video child task."""
import json
from sqlalchemy import select
from . import models as m
from .configured_task_repository import ConfiguredTaskRepository
from .errors import EngineError
from .video_configuration import configuration


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
    parent_id = video.get('parent_task_id', params.get('parent_task_id'))
    if type(parent_id) is not int or parent_id == child['id']:
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    if params.get('parent_task_id', parent_id) != parent_id:
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    parents = repo.rows(agent, parent_id)
    if not parents or parents[0]['tipo'] == 'VIDEO_GENERAR' or (parents[0]['parametros'] or {}).get('_deleted_at'):
        raise EngineError('VIDEO_PARENT_NOT_AUTHORIZED', 403)
    # Explicitly choose the latest persisted parent investigation. No provider calls,
    # no raw worker drafts, and no other agent's or owner's history.
    query = select(m.results.c.id, m.results.c.job_id, m.results.c.payload).join(m.jobs,
        (m.results.c.job_id == m.jobs.c.id) & (m.results.c.owner_id == m.jobs.c.owner_id)).where(
            m.jobs.c.owner_id == job['owner_id'], m.jobs.c.agent_id == job['agent_id'],
            m.jobs.c.legacy_task_id == parent_id, m.jobs.c.state.in_(['REVIEWING', 'DELIVERED'])
        ).order_by(m.jobs.c.created_at.desc(), m.jobs.c.id.desc(), m.results.c.version.desc()).limit(1)
    result = conn.execute(query).mappings().first()
    context = {'task_id': child['id'], 'parent_task_id': parent_id,
               'configuration_revision': params.get('_configuration_revision', 1),
               'name': child['nombre'], 'video': video, 'results': []}
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
