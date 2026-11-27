"""Verify delivered video evidence before using the shared service settlement."""
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import inspect, or_, select, update

from services.agent_point_status import context, cost
from services.scraping_quota import operaciones
from . import models as m
from .errors import EngineError
from .service_settlement import settle_units
from .video_costs import commercial_charge, commercial_points


def evidence(conn, owner, job_id, lock=False, require_price=True):
    job = select(m.jobs).where(m.jobs.c.owner_id == owner, m.jobs.c.id == job_id)
    job = conn.execute(job.with_for_update() if lock else job).mappings().first()
    if not job or job['state'] != 'DELIVERED':
        raise EngineError('SERVICE_DELIVERY_UNCONFIRMED', 409)
    task_query = select(m.tasks).where(m.tasks.c.owner_id == owner, m.tasks.c.job_id == job_id,
        m.tasks.c.tool_id == 'dpia.video.produce', m.tasks.c.state == 'COMPLETED')
    tasks = conn.execute(task_query.with_for_update() if lock else task_query).mappings().all()
    result_query = select(m.results).where(m.results.c.owner_id == owner, m.results.c.job_id == job_id
        ).order_by(m.results.c.version.desc()).limit(1)
    result = conn.execute(result_query.with_for_update() if lock else result_query).mappings().first()
    if len(tasks) != 1:
        raise EngineError('SERVICE_PRODUCTION_TASK_UNCONFIRMED', 409)
    if not result:
        raise EngineError('SERVICE_PERSISTED_RESULT_MISSING', 409)
    task = tasks[0]
    video = (task['output'] or {}).get('video') or {}
    persisted = (result['payload'] or {}).get('video') or {}
    reservation = video.get('cost') or {}
    operation = str(uuid5(NAMESPACE_URL, 'agents-video:' + task['id']))
    if (not task.get('provider_job_id') or task.get('provider_job_id') != video.get('remote_id')
            or video.get('state') != 'COMPLETED' or persisted.get('state') != 'COMPLETED'
            or persisted.get('remote_id') != video['remote_id'] or not persisted.get('url')
            or reservation.get('operation') != operation
            or (persisted.get('cost') or {}).get('operation') != operation
            or type(reservation.get('reserved_credits')) is not int):
        raise EngineError('SERVICE_RESULT_UNCONFIRMED', 409)
    legal = reservation.get('commercial')
    if legal is None:
        unit = conn.execute(select(operaciones).where(operaciones.c.usuario_id == owner,
            operaciones.c.operacion_id == str(uuid5(NAMESPACE_URL, operation + ':0')))).mappings().first()
        legal = context(unit).get('commercial') if unit else None
    if require_price:
        commercial_points(legal)
        if legal.get('pricing_model') == 'duration':
            persisted_cost = persisted.get('cost') or {}
            if any(reservation.get(key) != persisted_cost.get(key) for key in ('delivered_seconds', 'duration_source')):
                raise EngineError('SERVICE_DURATION_UNCONFIRMED', 409)
    return job, task, result, reservation, legal


def settle(conn, owner, job_id, now, *, dry_run=False):
    job, task, result, reservation, legal = evidence(conn, owner, job_id, lock=not dry_run)
    operation = reservation['operation']
    charged, amount = commercial_charge(legal, reservation)
    totals = settle_units(conn, owner=owner, service='video', operation=operation, dry_run=dry_run,
        reserved=reservation['reserved_credits'], authorized=charged, now=now,
        receipt={'job_id': job_id, 'result_id': result['id'], 'settled_amount': amount}, binding={'video_operation': operation, 'job_id': job_id,
                 'task_id': task['id'], 'agent_id': job['agent_id'], 'commercial': legal})
    cost = {**reservation, **totals, 'commercial': legal, 'settled_amount': amount,
            'commercial_reconciliation': 'SETTLED', 'result_id': result['id']}
    if not dry_run:
        persist_cost(conn, owner, task, result, cost)
    return cost


def persist_cost(conn, owner, task, result, cost):
    for table, row, column in [(m.tasks, task, 'output'), (m.results, result, 'payload')]:
        payload = dict(row[column])
        payload['video'] = {**payload['video'], 'cost': cost}
        conn.execute(update(table).where(table.c.owner_id == owner, table.c.id == row['id'])
                     .values(**{column: payload}))


def recover(conn, now, limit):
    if not inspect(conn).has_table(operaciones.name):
        return []
    cost_json = m.tasks.c.output['video']['cost']
    model = cost_json['commercial']['pricing_model'].as_string()
    candidates = conn.execute(select(m.jobs.c.owner_id, m.jobs.c.id)
        .join(m.tasks, (m.tasks.c.owner_id == m.jobs.c.owner_id) & (m.tasks.c.job_id == m.jobs.c.id))
        .where(m.jobs.c.state == 'DELIVERED', m.tasks.c.tool_id == 'dpia.video.produce',
               m.tasks.c.state == 'COMPLETED',
               cost_json['commercial']['points'].as_integer() > 0,
               cost_json['commercial_reconciliation'].as_string().is_(None),
               or_(model == 'fixed', (model == 'duration') &
                   cost_json['delivered_seconds'].as_string().is_not(None)))
        .order_by(m.jobs.c.updated_at.desc(), m.jobs.c.id)).all()
    settled = []
    for owner, job_id in candidates:
        try:
            with conn.begin_nested():
                settle(conn, owner, job_id, now)
                settled.append(job_id)
            if len(settled) >= limit:
                break
        except EngineError:
            continue
    return settled


def recover_isolated(engine, now, limit, logger):
    # Outbox publishing has already committed. Economic failures can only roll back this transaction.
    try:
        with engine.begin() as conn:
            return recover(conn, now, limit)
    except Exception as error:
        logger.error('Video economic recovery failed (%s)', type(error).__name__)
        return []


def diagnose(conn):
    """Read-only inventory across services, including legacy reservations."""
    rows = conn.execute(select(operaciones).where(
        operaciones.c.estado.in_(('reserved', 'dispatching', 'pending'))
    )).mappings()
    grouped = {}
    for row in rows:
        meta = context(row)
        operation = meta.get('service_operation') or meta.get('video_operation') or row['operacion_id']
        key = (row['usuario_id'], row['origen'], operation)
        item = grouped.setdefault(key, dict(owner_id=key[0], service=key[1], operation=operation,
            job_id=meta.get('job_id'), task_id=meta.get('task_id'), units=0, points=0, states=set()))
        item['units'] += 1
        item['points'] += cost(row)
        item['states'].add(row['estado'])
    for item in grouped.values():
        item['states'] = sorted(item['states'])
        item['decision'] = 'REVIEW'
        item['reason'] = 'SERVICE_EVIDENCE_REQUIRED'
        if item['service'] == 'video' and item['job_id']:
            try:
                settlement = settle(conn, item['owner_id'], item['job_id'], None, dry_run=True)
                if settlement['operation'] != item['operation']:
                    raise EngineError('SERVICE_RESERVATION_CONFLICT', 409)
                item.update(decision='SETTLE', reason='AUTHORIZED_DELIVERY',
                            authorized_points=settlement['consumed_credits'])
            except EngineError as error:
                item['reason'] = error.code
                item['missing_evidence'] = {
                    'SERVICE_PRICE_UNCONFIRMED': ['accepted_amount', 'currency', 'point_rate', 'policy_revision',
                                               'authorized_points'],
                    'SERVICE_PRICING_MODEL_UNCONFIRMED': ['accepted_fixed_or_duration_pricing_model'],
                    'SERVICE_DURATION_UNCONFIRMED': ['duration_from_matched_heygen_video'],
                    'SERVICE_DELIVERY_UNCONFIRMED': ['delivered_job_for_owner'],
                    'SERVICE_PRODUCTION_TASK_UNCONFIRMED': ['matching_completed_production_task'],
                    'SERVICE_PERSISTED_RESULT_MISSING': ['persisted_job_result'],
                    'SERVICE_RESULT_UNCONFIRMED': ['consistent_result_remote_id_and_reservation'],
                    'SERVICE_RESERVATION_CONFLICT': ['matching_ledger_units_and_authorization'],
                }.get(error.code, ['verified_service_evidence'])
                if error.code == 'SERVICE_DELIVERY_UNCONFIRMED' and item['states'] == ['reserved']:
                    task = conn.execute(select(m.tasks.c.id).join(m.jobs,
                        (m.jobs.c.owner_id == m.tasks.c.owner_id) & (m.jobs.c.id == m.tasks.c.job_id)
                    ).where(m.tasks.c.owner_id == item['owner_id'], m.jobs.c.id == item['job_id'],
                        m.tasks.c.id == item['task_id'], m.tasks.c.tool_id == 'dpia.video.produce',
                        m.jobs.c.state.in_(('FAILED', 'CANCELLED')), m.tasks.c.state.in_(('FAILED', 'CANCELLED')),
                        m.tasks.c.provider_submission_state == 'NOT_SUBMITTED', m.tasks.c.provider_job_id.is_(None)
                    )).scalar_one_or_none()
                    if task and str(uuid5(NAMESPACE_URL, 'agents-video:' + task)) == item['operation']:
                        item.update(decision='RELEASE', reason='TERMINAL_BEFORE_SUBMISSION')
                        item.pop('missing_evidence', None)
        yield item


def resolve_historical(conn, principal, job_id, operation, result_id, action, reference):
    """Apply an audited explicit resolution, preserving the original price evidence."""
    from .auth import now_utc
    from .management import audit_agent

    owner = conn.execute(select(m.jobs.c.owner_id).where(m.jobs.c.id == job_id)).scalar_one_or_none()
    if owner is None:
        raise EngineError('job_not_found', 404)
    job, task, result, reservation, legal = evidence(conn, owner, job_id, lock=True, require_price=False)
    if reservation['operation'] != operation or result['id'] != result_id:
        raise EngineError('SERVICE_RESERVATION_CONFLICT', 409)
    resolution = {'action': action, 'reference': reference, 'actor_id': principal.actor_id}
    if reservation.get('administrative_resolution') == resolution:
        return reservation
    if reservation.get('commercial_reconciliation') in ('SETTLED', 'WAIVED'):
        raise EngineError('SERVICE_RESERVATION_CONFLICT', 409)
    now = now_utc()
    if action == 'retry_verified':
        cost = settle(conn, owner, job_id, now)
    elif action == 'refresh_duration':
        seconds = fetch_historical_duration(conn, job, task)
        cost = {**reservation, 'delivered_seconds': seconds, 'duration_source': 'HEYGEN_VIDEO_RESPONSE',
                'result_id': result_id}
    else:
        cost = {**reservation, 'commercial_reconciliation': 'ADMIN_HOLD', 'result_id': result_id}
        if action == 'waive':
            totals = settle_units(conn, owner=owner, service='video', operation=operation,
                reserved=reservation['reserved_credits'], authorized=0, now=now,
                receipt={'job_id': job_id, 'result_id': result_id, 'settled_amount': '0',
                         'administrative_resolution': resolution},
                binding={'video_operation': operation, 'job_id': job_id, 'task_id': task['id'],
                         'agent_id': job['agent_id'], 'commercial': legal})
            cost.update(totals, commercial_reconciliation='WAIVED', settled_amount='0')
    cost['administrative_resolution'] = resolution
    persist_cost(conn, owner, task, result, cost)
    agent = conn.execute(select(m.agents).where(m.agents.c.id == job['agent_id'],
        m.agents.c.owner_id == owner)).mappings().one()
    audit_agent(conn, principal, agent, 'VIDEO_COMMERCIAL_RESOLUTION',
                {'job_id': job_id, 'operation': operation, 'result_id': result_id, **resolution}, now)
    return cost



def fetch_historical_duration(conn, job, task):
    import json
    import re
    from flask import current_app
    from .rest_providers.service import Service
    from .shared_video_provider import resolve
    from .video_costs import measured_duration

    remote = task['provider_job_id']
    observed = conn.execute(select(m.usage.c.id).where(m.usage.c.owner_id == job['owner_id'],
        m.usage.c.job_id == job['id'], m.usage.c.provider_id == 'heygen.rest',
        m.usage.c.provider_record_id == remote, m.usage.c.verified.is_(True))).first()
    if not observed or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', remote):
        raise EngineError('SERVICE_PROVIDER_REFERENCE_UNCONFIRMED', 409)
    provider = resolve(conn, job['owner_id'])
    if not provider['credential_ciphertext'] or provider['credential_origin'] != provider['base_url']:
        raise EngineError('rest_provider_not_ready', 409)
    service = Service(conn.engine, current_app.config)
    secret = json.loads(service.secrets.decrypt(provider))
    if not isinstance(secret, str) or not secret:
        raise EngineError('rest_provider_not_ready', 409)
    status, response = service.http.get(provider['base_url'], '/v3/videos/' + remote, secret,
                                        'X-Api-Key', provider['timeout_seconds'])
    video = response.get('data') if isinstance(response, dict) else None
    if status != 200 or not isinstance(video, dict) or video.get('id') != remote or video.get('status') != 'completed':
        raise EngineError('SERVICE_DURATION_UNCONFIRMED', 409)
    seconds = measured_duration(video)
    if seconds is None:
        raise EngineError('SERVICE_DURATION_UNCONFIRMED', 409)
    return seconds
