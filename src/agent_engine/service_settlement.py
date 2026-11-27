"""Settle unit reservations in the shared ledger after a service verifies delivery."""
import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, update

from services.agent_point_status import context, cost, locked_balance
from services.scraping_quota import operaciones
from .errors import EngineError


def settle_units(conn, *, owner, service, operation, reserved, authorized, binding, now, receipt=None, dry_run=False):
    if (type(reserved) is not int or type(authorized) is not int
            or not 0 <= authorized <= reserved <= 1000 or reserved == 0):
        raise EngineError('SERVICE_RESERVATION_CONFLICT', 409)
    if not dry_run:
        locked_balance(conn, owner)
    identifiers = {str(uuid5(NAMESPACE_URL, f'{operation}:{index}')): index for index in range(reserved)}
    query = select(operaciones).where(
        operaciones.c.usuario_id == owner, operaciones.c.operacion_id.in_(identifiers)
    )
    rows = conn.execute(query if dry_run else query.with_for_update()).mappings().all()
    if len(rows) != reserved:
        raise EngineError('SERVICE_RESERVATION_CONFLICT', 409)
    transitions = {}
    for row in rows:
        info = context(row)
        index = identifiers[row['operacion_id']]
        desired = 'consumed' if index < authorized else 'released'
        if (row['origen'] != service or cost(row) != 1 or info.get('unit') != index
                or any(info.get(key) != value for key, value in binding.items())
                or row['estado'] not in ('pending', desired)):
            raise EngineError('SERVICE_RESERVATION_CONFLICT', 409)
        if row['estado'] != desired:
            transitions.setdefault(desired, []).append(row['operacion_id'])
    for desired, ids in ({} if dry_run else transitions).items():
        values = {'estado': desired, 'actualizado_en': now}
        if receipt:
            values['resultado_json'] = json.dumps(receipt)
        conn.execute(update(operaciones).where(operaciones.c.usuario_id == owner,
            operaciones.c.operacion_id.in_(ids)).values(**values))
    return {'consumed_credits': authorized, 'released_credits': reserved - authorized}
