"""Preview v1 missing names; --apply is an explicit manual opt-in after review.

Uses a supplied SQLAlchemy URL. Never imports app/config or loads credentials.
Default mode rolls back. All writes change nombre only, inside one transaction.
"""
import argparse
import json
import sys
from pathlib import Path
from sqlalchemy import create_engine, MetaData, Table
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.task_name_backfill import migrate_v1_names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url-env', default='TASK_NAMES_DATABASE_URL', help='Environment variable holding SQLAlchemy URL')
    parser.add_argument('--apply', action='store_true', help='Commit name-only changes after review')
    args = parser.parse_args()
    import os
    url = os.environ.get(args.url_env)
    if not url:
        parser.error('Set the database URL environment variable explicitly; no connection attempted.')
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                metadata = MetaData()
                tasks = Table('agente_tareas', metadata, autoload_with=conn, resolve_fks=False)
                agents = Table('agentes', metadata, autoload_with=conn, resolve_fks=False)
                changes = migrate_v1_names(conn, tasks, agents)
                print(json.dumps({'mode':'apply' if args.apply else 'preview', 'changes':changes}, ensure_ascii=False, indent=2))
                if args.apply:
                    transaction.commit()
                else:
                    transaction.rollback()
            except Exception:
                transaction.rollback()
                raise
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
