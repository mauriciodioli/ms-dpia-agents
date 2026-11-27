"""Video cost conversion and unit reservations in the existing shared point ledger.

A unit row costs one point in both existing channels; no change to balances or
POINT_COST is needed. No invented provider tariff and no fallback to zero cost.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select, insert, update
from services.agent_point_status import locked_balance, cost, context, period_window
from services.scraping_quota import operaciones
from .errors import EngineError


def positive(value, code):
    try:
        if isinstance(value, bool):raise InvalidOperation()
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0:raise InvalidOperation()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise EngineError(code,409) from None


def credits(usd, config):
    rate = positive(config.get('AGENTS_VIDEO_USD_PER_CREDIT'), 'VIDEO_COST_RATE_NOT_CONFIGURED')
    amount = positive(usd, 'VIDEO_COST_NOT_VERIFIABLE')
    return int((amount / rate).to_integral_value(rounding=ROUND_CEILING))


def commercial_points(quote):
    if (not isinstance(quote, dict) or quote.get('currency') != 'USD'
            or type(quote.get('policy_revision')) is not int or quote['policy_revision'] < 1
            or type(quote.get('points')) is not int or not 0 < quote['points'] <= 1000):
        raise EngineError('SERVICE_PRICE_UNCONFIRMED', 409)
    expected = credits(quote.get('amount'), {'AGENTS_VIDEO_USD_PER_CREDIT': quote.get('usd_per_credit')})
    if expected != quote['points']:
        raise EngineError('SERVICE_PRICE_UNCONFIRMED', 409)
    return expected


def priced_video(estimated_amount, policy):
    rate = positive(policy['usd_per_credit'], 'VIDEO_COST_RATE_NOT_CONFIGURED')
    points = credits(estimated_amount, {'AGENTS_VIDEO_USD_PER_CREDIT': rate})
    return {'currency': 'USD', 'usd_per_credit': str(rate), 'points': points,
            'policy_revision': policy['revision'], 'amount': str(points * rate)}


def authorize_video(production, classification, estimate, policy):
    """Freeze the commercial terms before submitting to the provider."""
    if classification is not None:
        commercial_points(classification)
        return classification
    if production.get('commercial_approval') is not True:
        return None
    authorized = {
        **priced_video(estimate['estimated_usd'], policy),
        'pricing_model': 'duration', 'authorized_seconds': production['duration_seconds'],
        'duration_base_amount': estimate['estimated_usd'],
        'authorization': 'configured_limit', 'max_points': production['budget_credits'],
    }
    commercial_points(authorized)
    return authorized


def measured_duration(response):
    """Accept only a numeric duration from the matched provider response."""
    value = response.get('duration')
    if type(value) not in (int, float):
        return None
    try:
        duration = positive(value, 'SERVICE_DURATION_UNCONFIRMED')
    except EngineError:
        return None
    return str(duration)


def commercial_charge(quote, cost):
    points = commercial_points(quote)
    ceiling = positive(quote['amount'], 'SERVICE_PRICE_UNCONFIRMED')
    model = quote.get('pricing_model')
    if model == 'fixed':
        return points, str(ceiling)
    if model != 'duration':
        raise EngineError('SERVICE_PRICING_MODEL_UNCONFIRMED', 409)
    if type(quote.get('authorized_seconds')) is not int or quote['authorized_seconds'] <= 0:
        raise EngineError('SERVICE_PRICE_UNCONFIRMED', 409)
    if cost.get('duration_source') != 'HEYGEN_VIDEO_RESPONSE':
        raise EngineError('SERVICE_DURATION_UNCONFIRMED', 409)
    duration = positive(cost.get('delivered_seconds'), 'SERVICE_DURATION_UNCONFIRMED')
    authorized_duration = Decimal(quote['authorized_seconds'])
    base = positive(quote.get('duration_base_amount', ceiling), 'SERVICE_PRICE_UNCONFIRMED')
    if base > ceiling:
        raise EngineError('SERVICE_PRICE_UNCONFIRMED', 409)
    amount = base * min(duration, authorized_duration) / authorized_duration
    return credits(amount, {'AGENTS_VIDEO_USD_PER_CREDIT': quote['usd_per_credit']}), str(amount)


def reserve(conn, job, task, usd, config, production, quote_reference, now, commercial=None):
    """Caller supplies a verified provider quote, never a browser estimate."""
    if not production['automatic_production']:
        raise EngineError('VIDEO_PRODUCTION_APPROVAL_REQUIRED',409)
    validate_storage(conn)
    units = commercial_points(commercial) if commercial is not None else credits(usd, config)
    if type(production['budget_credits']) is not int or units > production['budget_credits']:
        raise EngineError('VIDEO_BUDGET_INSUFFICIENT',409)
    if not isinstance(quote_reference,str) or not quote_reference.strip():
        raise EngineError('VIDEO_COST_NOT_VERIFIABLE',409)
    # Bound unit-row work; large quotes require an amount-aware shared ledger.
    if units > 1000:raise EngineError('VIDEO_RESERVATION_LIMIT',409)
    from . import point_ledger, models as m
    agent = conn.execute(select(m.agents).where(m.agents.c.id==job['agent_id'],
        m.agents.c.owner_id==job['owner_id']).with_for_update()).mappings().one()
    policy = point_ledger.policy(conn, agent)
    if not policy:raise EngineError('AGENT_BUDGET_MISSING',409)
    window = period_window(policy['periodo_presupuesto'],policy['zona_horaria'],now)
    total, held = locked_balance(conn,job['owner_id'])
    operation = str(uuid5(NAMESPACE_URL,'agents-video:'+task['id']))
    own = [r for r in held if context(r).get('video_operation')==operation]
    digest = hashlib.sha256(json.dumps({'usd':str(usd),'rate':str(config.get('AGENTS_VIDEO_USD_PER_CREDIT')),
        'quote':quote_reference,'input':task['input_snapshot'], **({'commercial': commercial} if commercial else {})},sort_keys=True).encode()).hexdigest()
    previous = conn.execute(select(operaciones).where(operaciones.c.usuario_id==job['owner_id'],
        operaciones.c.operacion_id==str(uuid5(NAMESPACE_URL,operation+':0'))).with_for_update()).mappings().first()
    if previous:
        if previous['solicitud_hash']!=digest:raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
        if len(own)!=units or any(r['estado']!='reserved' for r in own):
            raise EngineError('VIDEO_OPERATION_NOT_REPLAYABLE',409)
        return {'operation':operation,'reserved_credits':units,'usd_per_credit':str(config['AGENTS_VIDEO_USD_PER_CREDIT']),
                'estimated_usd':str(usd),'quote_reference':quote_reference, **({'commercial': commercial} if commercial else {})}
    if total-sum(cost(r) for r in held)<units:raise EngineError('INSUFFICIENT_POINTS',409)
    used = sum(cost(r) for r in held if context(r).get('agent_id')==job['agent_id'] and context(r).get('period')==window['key'])
    if used+units>policy['presupuesto_puntos_periodo']:raise EngineError('AGENT_BUDGET_EXHAUSTED',409)
    metadata={'video_operation':operation,'agent_id':job['agent_id'],'job_id':job['id'],
        'task_id':task['id'],'period':window['key'],'usd_per_credit':str(config['AGENTS_VIDEO_USD_PER_CREDIT']),
        'estimated_usd':str(usd),'quote_reference':quote_reference, **({'commercial': commercial} if commercial else {})}
    for index in range(units):
        conn.execute(insert(operaciones).values(operacion_id=str(uuid5(NAMESPACE_URL,operation+':'+str(index))),
            usuario_id=job['owner_id'],solicitud_hash=digest,origen='video',estado='reserved',
            contexto_json=json.dumps({**metadata,'unit':index}),creado_en=now,actualizado_en=now))
    return {'operation':operation,'reserved_credits':units,'usd_per_credit':metadata['usd_per_credit'],
            'estimated_usd':str(usd),'quote_reference':quote_reference, **({'commercial': commercial} if commercial else {})}


def reconcile(conn, owner, job_id, remote_id, actual_usd):
    """Record attributable provider evidence independently of commercial points."""
    from . import models as m

    try:
        if isinstance(actual_usd, bool):
            raise InvalidOperation()
        actual = Decimal(str(actual_usd))
        if not actual.is_finite() or actual < 0 or actual >= 10**10 or actual != actual.quantize(Decimal('0.00000001')):
            raise InvalidOperation()
    except InvalidOperation:
        raise EngineError('VIDEO_COST_NOT_VERIFIABLE', 409) from None
    usage = conn.execute(update(m.usage).where(
        m.usage.c.owner_id == owner, m.usage.c.job_id == job_id,
        m.usage.c.provider_id == 'heygen.rest', m.usage.c.provider_record_id == remote_id
    ).values(cost=actual, currency='USD', verified=True, evidence_source='ADMIN_PROVIDER_DOCUMENT'))
    if usage.rowcount != 1:
        raise EngineError('VIDEO_PROVIDER_USAGE_UNCONFIRMED', 409)
    return {'actual_usd': str(actual_usd), 'reconciliation': 'CONFIRMED'}


def transition(conn,owner,reservation,state,now):
    if state not in ('dispatching','pending','released'):raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
    locked_balance(conn,owner)
    identifiers=[str(uuid5(NAMESPACE_URL,reservation['operation']+':'+str(i))) for i in range(reservation['reserved_credits'])]
    rows=conn.execute(select(operaciones).where(operaciones.c.usuario_id==owner,
        operaciones.c.operacion_id.in_(identifiers)).with_for_update()).mappings().all()
    if len(rows)!=reservation['reserved_credits']:raise EngineError('VIDEO_RESERVATION_CONFLICT',409)
    for row in rows:
        if row['estado'] in ('consumed','released') and row['estado']!=state:raise EngineError('VIDEO_OPERATION_NOT_REPLAYABLE',409)
    conn.execute(update(operaciones).where(operaciones.c.usuario_id==owner,
        operaciones.c.operacion_id.in_(identifiers)).values(estado=state,actualizado_en=now))


def validate_storage(conn):
    from sqlalchemy import inspect,text
    from sqlalchemy.exc import SQLAlchemyError
    import re
    inspector=inspect(conn)
    try:
        if not inspector.has_table('pwa_scraping_operaciones') or not inspector.has_table('pwa_scraping_cupos'):
            raise EngineError('VIDEO_LEDGER_SCHEMA_INCOMPATIBLE',503)
        if conn.dialect.name=='mysql':
            engines=conn.execute(text("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('pwa_scraping_operaciones','pwa_scraping_cupos')")).scalars().all()
            if len(engines)!=2 or any(value.lower()!='innodb' for value in engines):
                raise EngineError('VIDEO_LEDGER_SCHEMA_INCOMPATIBLE',503)
            columns={c['name']:c for c in inspector.get_columns('pwa_scraping_operaciones')}
            if not set(operaciones.c.keys())<=set(columns):raise EngineError('VIDEO_LEDGER_SCHEMA_INCOMPATIBLE',503)
            for field,values in (('origen',('video',)),('estado',('reserved','dispatching','pending','consumed','released'))):
                kind=columns[field]['type']
                if getattr(kind,'enums',None) and not set(values)<=set(kind.enums):
                    raise EngineError('VIDEO_LEDGER_SCHEMA_INCOMPATIBLE',503)
                minimum = 80 if field == 'origen' and not getattr(kind,'enums',None) else max(map(len,values))
                if getattr(kind,'length',None) is not None and kind.length<minimum:
                    raise EngineError('VIDEO_LEDGER_SCHEMA_INCOMPATIBLE',503)
                for check in inspector.get_check_constraints('pwa_scraping_operaciones'):
                    expression=check.get('sqltext','').replace('`','')
                    if re.search(r'\b'+field+r'\b',expression,re.I):
                        # Evaluate the actual database CHECK read-only, with a bound
                        # prospective value. Complex cross-column checks fail closed.
                        expression=re.sub(r'\b'+field+r'\b',':check_value',expression,flags=re.I)
                        for value in values:
                            accepted=conn.execute(text('SELECT CASE WHEN ('+expression+') THEN 1 ELSE 0 END'),{'check_value':value}).scalar_one()
                            if accepted!=1:raise EngineError('VIDEO_LEDGER_SCHEMA_INCOMPATIBLE',503)
    except (SQLAlchemyError,KeyError,AttributeError):
        raise EngineError('VIDEO_LEDGER_SCHEMA_INCOMPATIBLE',503) from None
