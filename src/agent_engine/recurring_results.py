"""Stable schedule snapshot and append-only update log; runs remain auditable."""
import json
from uuid import uuid4
from sqlalchemy import select, insert, update
from . import models as m


def record_success(conn, job, result_id, payload, now):
    """Must be called in the same transaction that persists the completed result."""
    schedule_id = job.get('schedule_id')
    if not schedule_id:
        return
    current = conn.execute(select(m.schedule_current).where(
        m.schedule_current.c.owner_id == job['owner_id'],
        m.schedule_current.c.schedule_id == schedule_id).with_for_update()).mappings().first()
    if current:
        changed = json.dumps(current['payload'], sort_keys=True, default=str) != json.dumps(payload, sort_keys=True, default=str)
        version = current['version'] + int(changed)
        conn.execute(update(m.schedule_current).where(
            m.schedule_current.c.owner_id == job['owner_id'],
            m.schedule_current.c.schedule_id == schedule_id).values(
                latest_job_id=job['id'], latest_result_id=result_id,
                payload=payload if changed else current['payload'], version=version,
                last_checked_at=now,
                last_changed_at=now if changed else current['last_changed_at']))
    else:
        changed = True
        version = 1
        conn.execute(insert(m.schedule_current).values(
            owner_id=job['owner_id'], schedule_id=schedule_id, agent_id=job['agent_id'],
            first_job_id=job['id'], latest_job_id=job['id'], latest_result_id=result_id,
            payload=payload, version=version, first_seen_at=now,
            last_checked_at=now, last_changed_at=now))
    conn.execute(insert(m.schedule_updates).values(
        id=str(uuid4()), owner_id=job['owner_id'], schedule_id=schedule_id,
        job_id=job['id'], result_id=result_id, version=version,
        changed=changed, message=('Resultado actualizado' if current else 'Resultado inicial') if changed else 'Comprobado sin cambios',
        checked_at=now, payload=payload))
