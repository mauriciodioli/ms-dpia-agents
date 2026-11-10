"""Opt-in, DB-backed ingestion. No DDL, provider calls, or startup side effects.

Only trusted producers with an issued API-client id may write to ae_task_inbox.
Each row is authenticated against the current client grants before submission.
"""
from datetime import datetime
from sqlalchemy import Table, Column, String, Integer, DateTime, JSON, MetaData, UniqueConstraint, select, update
from .auth import Principal, active_user, now_utc
from .contracts import SCOPES
from .dispatcher import Dispatcher
from .errors import EngineError
from . import models as m

inbox = Table('ae_task_inbox', MetaData(),
    Column('id', String(36), primary_key=True),
    Column('owner_id', Integer, nullable=False),
    Column('client_id', String(36), nullable=False),
    Column('agent_id', String(36), nullable=False),
    Column('idempotency_key', String(128), nullable=False),
    Column('request_payload', JSON, nullable=False),
    Column('state', String(20), nullable=False),
    Column('job_id', String(36)),
    Column('error_code', String(80)),
    Column('created_at', DateTime, nullable=False),
    Column('processed_at', DateTime),
    UniqueConstraint('owner_id', 'client_id', 'idempotency_key', name='uq_ae_task_inbox_dedupe'))


def tick(conn, batch_size=50):
    """Process a bounded batch in the caller's transaction.

    Database row locking and Dispatcher idempotency make retries safe. Invalid
    entries are recorded as REJECTED without blocking subsequent entries.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise EngineError('invalid_batch_size')
    now = now_utc()
    rows = conn.execute(select(inbox).where(inbox.c.state == 'PENDING')
        .order_by(inbox.c.created_at, inbox.c.id).limit(batch_size)
        .with_for_update(skip_locked=True)).mappings().all()
    counts = {'accepted': 0, 'rejected': 0}
    for row in rows:
        try:
            # Savepoint prevents a rejected submission from leaving partial job rows.
            with conn.begin_nested():
                job = _submit_row(conn, row, now)
        except EngineError as exc:
            conn.execute(update(inbox).where(inbox.c.id == row['id']).values(
                state='REJECTED', error_code=exc.code, processed_at=now))
            counts['rejected'] += 1
        else:
            conn.execute(update(inbox).where(inbox.c.id == row['id']).values(
                state='ACCEPTED', job_id=job['id'], processed_at=now))
            counts['accepted'] += 1
    return counts


def _submit_row(conn, row, now):
    active_user(conn, row['owner_id'])
    client = conn.execute(select(m.clients).where(
        m.clients.c.id == row['client_id'],
        m.clients.c.owner_id == row['owner_id'])).mappings().first()
    if (client is None or client['revoked_at'] is not None or
        client['expires_at'] <= now or 'jobs:create' not in (client['scopes'] or [])):
        raise EngineError('inbox_client_not_authorized', 403)
    grants = frozenset(conn.execute(select(m.client_grants.c.agent_id).where(
        m.client_grants.c.owner_id == row['owner_id'],
        m.client_grants.c.client_id == row['client_id'])).scalars())
    principal = Principal(row['owner_id'], 'API_CLIENT', row['client_id'],
        frozenset(client['scopes']), bool(client['all_agents']), grants)
    job, _ = Dispatcher(conn).submit(principal, row['agent_id'],
        row['request_payload'], row['idempotency_key'])
    return job
