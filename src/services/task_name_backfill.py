"""Idempotent v1 repair. Only the nombre column is written; caller owns transaction."""
from sqlalchemy import select, update
from services.task_names import legacy_task_name


def fill_missing_v1_names(conn, tasks, agent_id, city=''):
    rows = conn.execute(select(tasks).where(tasks.c.agente_id == agent_id)
                        .with_for_update()).mappings().all()
    changes = []
    for row in rows:
        if ((row['parametros'] or {}).get('schema_version') != 1
                or (row['nombre'] is not None and row['nombre'].strip())):
            continue
        name = legacy_task_name(row, city=city)
        old = tasks.c.nombre.is_(None) if row['nombre'] is None else tasks.c.nombre == row['nombre']
        # MySQL has ON UPDATE CURRENT_TIMESTAMP: explicitly preserve this column.
        conn.execute(update(tasks).where(tasks.c.id == row['id'], old).values(
            nombre=name, actualizado_en=tasks.c.actualizado_en))
        changes.append({'id': row['id'], 'name': name})
    return changes


def migrate_v1_names(conn, tasks, agents):
    """Repair registered agents' tasks, including paused and unlinked v1 rows."""
    changes = []
    for agent in conn.execute(select(agents.c.id, agents.c.ciudad)).mappings().all():
        changes.extend(fill_missing_v1_names(conn, tasks, agent['id'], agent['ciudad'] or ''))
    return changes
