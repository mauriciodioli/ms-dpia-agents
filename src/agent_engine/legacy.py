"""Explicit read-only bridge; does not change or auto-import legacy agents."""
from .errors import EngineError


def legacy_projection(store, owner_id: int) -> dict | None:
    if type(owner_id) is not int or owner_id <= 0:
        raise EngineError('invalid_owner')
    record = store.get(owner_id)
    if record is None:
        return None
    # Deliberately a separate namespace, not a native engine UUID.
    return {'reference': {'namespace': 'legacy', 'id': record['id']},
            'owner_id': owner_id, 'revision': record['revision'],
            'configuration_state': 'DISABLED', 'execution_available': False,
            'configuration': record['configuration']}
