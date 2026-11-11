"""Additive schema, separate from db.Model.metadata. No DDL runs on import.

owner_id is the existing usuarios.id. No legacy table is created or altered.
Composite tenant keys prevent cross-owner references within engine tables.
"""
from sqlalchemy import (MetaData, Table, Column, String, Integer, BigInteger, Boolean,
                        DateTime, JSON, Text, Numeric, UniqueConstraint, ForeignKey,
                        ForeignKeyConstraint, CheckConstraint, Index, text)
from .states import AgentState, JobState

metadata = MetaData(naming_convention={
    'ix': 'ix_%(table_name)s_%(column_0_name)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'ck': 'ck_%(table_name)s_%(constraint_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
})


def identity():
    return [Column('id', String(36), primary_key=True), Column('owner_id', Integer, nullable=False),
            UniqueConstraint('owner_id', 'id')]


def tenant_ref(column, target):
    return ForeignKeyConstraint(['owner_id', column], [target + '.owner_id', target + '.id'])


agents = Table('ae_agents', metadata, *identity(),
    Column('name', String(120), nullable=False), Column('description', Text, nullable=False),
    Column('instructions', Text, nullable=False), Column('timezone', String(64), nullable=False),
    Column('configuration_state', String(20), nullable=False, server_default='DISABLED'),
    Column('revision', Integer, nullable=False, server_default='1'),
    Column('limits', JSON, nullable=False), Column('search_parameters', JSON, nullable=False),
    Column('legacy_agent_id', BigInteger, nullable=True, unique=True),
    Column('created_at', DateTime, nullable=False), Column('updated_at', DateTime, nullable=False),
    CheckConstraint("configuration_state IN ('ENABLED','DISABLED')", name='configuration_state'),
    CheckConstraint('revision >= 1', name='revision_positive'),
    CheckConstraint('owner_id > 0', name='owner_positive'),
    Index('ix_ae_agents_owner_created', 'owner_id', 'created_at', 'id'))

agent_capabilities = Table('ae_agent_capabilities', metadata,
    Column('owner_id', Integer, primary_key=True), Column('agent_id', String(36), primary_key=True),
    Column('tool_id', String(80), primary_key=True), tenant_ref('agent_id', 'ae_agents'))

agent_events = Table('ae_agent_events', metadata, *identity(),
    Column('agent_id', String(36), nullable=False), Column('revision', Integer, nullable=False),
    Column('action', String(40), nullable=False), Column('actor_type', String(32), nullable=False),
    Column('actor_id', String(120), nullable=False), Column('details', JSON, nullable=False),
    Column('created_at', DateTime, nullable=False), tenant_ref('agent_id', 'ae_agents'),
    Index('ix_ae_agent_events_history', 'owner_id', 'agent_id', 'created_at'))

clients = Table('ae_api_clients', metadata, *identity(),
    Column('name', String(120), nullable=False), Column('token_digest', String(64), nullable=False, unique=True),
    Column('scopes', JSON, nullable=False), Column('all_agents', Boolean, nullable=False),
    Column('expires_at', DateTime, nullable=False), Column('revoked_at', DateTime),
    Column('created_at', DateTime, nullable=False))

client_grants = Table('ae_client_agent_grants', metadata,
    Column('owner_id', Integer, primary_key=True), Column('client_id', String(36), primary_key=True),
    Column('agent_id', String(36), primary_key=True),
    tenant_ref('client_id', 'ae_api_clients'), tenant_ref('agent_id', 'ae_agents'))

security_events = Table('ae_security_events', metadata, *identity(),
    Column('client_id', String(36), nullable=False), Column('actor_id', String(120), nullable=False),
    Column('action', String(32), nullable=False), Column('created_at', DateTime, nullable=False),
    tenant_ref('client_id', 'ae_api_clients'),
    CheckConstraint("action IN ('CLIENT_CREATED','CLIENT_ROTATED','CLIENT_REVOKED')", name='security_action'))

providers = Table('ae_providers', metadata,
    Column('id', String(80), primary_key=True), Column('kind', String(24), nullable=False),
    Column('registry_key', String(120), nullable=False), Column('contract_version', String(40), nullable=False))

connections = Table('ae_provider_connections', metadata, *identity(),
    Column('provider_id', String(80), ForeignKey('ae_providers.id'), nullable=False),
    Column('name', String(120), nullable=False),
    # Reference to a server-managed secret, never a credential value or client input.
    Column('credential_ref', String(255), nullable=False),
    Column('enabled', Boolean, nullable=False), Column('created_at', DateTime, nullable=False))

tool_grants = Table('ae_agent_tool_grants', metadata,
    Column('owner_id', Integer, primary_key=True), Column('agent_id', String(36), primary_key=True),
    Column('tool_id', String(80), primary_key=True), Column('connection_id', String(36), nullable=False),
    tenant_ref('agent_id', 'ae_agents'), tenant_ref('connection_id', 'ae_provider_connections'))

schedules = Table('ae_schedules', metadata, *identity(),
    Column('agent_id', String(36), nullable=False), Column('timezone', String(64), nullable=False),
    Column('definition', JSON, nullable=False), Column('enabled', Boolean, nullable=False),
    Column('revision', Integer, nullable=False), Column('next_run_at', DateTime),
    Column('created_at', DateTime, nullable=False), tenant_ref('agent_id', 'ae_agents'))

jobs = Table('ae_jobs', metadata, *identity(),
    Column('agent_id', String(36), nullable=False), Column('client_id', String(36)),
    Column('schedule_id', String(36)), Column('schedule_slot', DateTime),
    Column('idempotency_key', String(128), nullable=False), Column('request_hash', String(64), nullable=False),
    Column('correlation_id', String(36), nullable=False), Column('state', String(32), nullable=False),
    Column('revision', Integer, nullable=False, server_default='1'),
    Column('agent_revision', Integer, nullable=False), Column('request_snapshot', JSON, nullable=False),
    Column('configuration_snapshot', JSON, nullable=False), Column('priority', Integer, nullable=False),
    Column('progress', Integer), Column('error_code', String(80)),
    Column('execute_at', DateTime), Column('deliver_not_before', DateTime), Column('deadline_at', DateTime),
    Column('started_at', DateTime), Column('finished_at', DateTime),
    Column('created_at', DateTime, nullable=False), Column('updated_at', DateTime, nullable=False),
    Column('correction_count', Integer, nullable=False, server_default='0'),
    tenant_ref('agent_id', 'ae_agents'), tenant_ref('client_id', 'ae_api_clients'),
    tenant_ref('schedule_id', 'ae_schedules'),
    UniqueConstraint('owner_id', 'agent_id', 'idempotency_key', name='uq_ae_jobs_agent_idempotency'),
    UniqueConstraint('owner_id', 'schedule_id', 'schedule_slot', name='uq_ae_jobs_schedule_slot'),
    CheckConstraint('state IN (' + ','.join("'" + state.value + "'" for state in JobState) + ')', name='job_state'),
    CheckConstraint('progress IS NULL OR (progress >= 0 AND progress <= 100)', name='progress_range'),
    CheckConstraint('priority >= 0 AND priority <= 9', name='priority_range'),
    CheckConstraint('revision >= 1 AND correction_count >= 0', name='revision_corrections'),
    Index('ix_ae_jobs_owner_agent_created', 'owner_id', 'agent_id', 'created_at', 'id'),
    Index('ix_ae_jobs_dispatch', 'state', 'execute_at', 'priority'))

tasks = Table('ae_tasks', metadata, *identity(),
    Column('job_id', String(36), nullable=False), Column('position', Integer, nullable=False),
    Column('tool_id', String(80), nullable=False), Column('state', String(32), nullable=False),
    Column('input_snapshot', JSON, nullable=False), Column('output', JSON),
    Column('lease_token', String(36)), Column('lease_until', DateTime),
    Column('lease_version', Integer, nullable=False, server_default='0'),
    Column('attempt_count', Integer, nullable=False, server_default='0'),
    Column('next_attempt_at', DateTime), Column('provider_job_id', String(160)),
    Column('provider_submission_state', String(32), nullable=False, server_default='NOT_SUBMITTED'),
    tenant_ref('job_id', 'ae_jobs'), UniqueConstraint('owner_id', 'job_id', 'position', name='uq_ae_tasks_job_position'),
    UniqueConstraint('owner_id', 'job_id', 'id', name='uq_ae_tasks_job_task'),
    CheckConstraint('position >= 0 AND attempt_count >= 0 AND lease_version >= 0', name='task_counters'),
    Index('ix_ae_tasks_recovery', 'state', 'lease_until', 'next_attempt_at'))

attempts = Table('ae_attempts', metadata, *identity(),
    Column('task_id', String(36), nullable=False), Column('number', Integer, nullable=False),
    Column('worker_id', String(120), nullable=False), Column('lease_token', String(36), nullable=False),
    Column('provider_id', String(80)), Column('provider_request_id', String(160)),
    Column('state', String(32), nullable=False), Column('error_code', String(80)),
    Column('started_at', DateTime, nullable=False), Column('finished_at', DateTime),
    tenant_ref('task_id', 'ae_tasks'), UniqueConstraint('owner_id', 'task_id', 'number', name='uq_ae_attempts_task_number'),
    CheckConstraint('number >= 1', name='attempt_positive'))

results = Table('ae_results', metadata, *identity(),
    Column('job_id', String(36), nullable=False), Column('version', Integer, nullable=False),
    Column('schema_version', String(40), nullable=False), Column('payload', JSON, nullable=False),
    Column('evidence_status', String(32), nullable=False), Column('created_at', DateTime, nullable=False),
    Column('approved_at', DateTime), tenant_ref('job_id', 'ae_jobs'),
    UniqueConstraint('owner_id', 'job_id', 'version', name='uq_ae_results_job_version'),
    UniqueConstraint('owner_id', 'job_id', 'id', name='uq_ae_results_job_result'),
    CheckConstraint('version >= 1', name='result_version'),
    CheckConstraint("evidence_status IN ('UNVERIFIED','SOURCE_REFERENCED','VERIFIED')", name='evidence'))

reviews = Table('ae_reviews', metadata, *identity(),
    Column('job_id', String(36), nullable=False), Column('result_id', String(36), nullable=False),
    Column('cycle', Integer, nullable=False), Column('decision', String(32), nullable=False),
    Column('reason_codes', JSON, nullable=False), Column('created_at', DateTime, nullable=False),
    ForeignKeyConstraint(['owner_id', 'job_id', 'result_id'], ['ae_results.owner_id', 'ae_results.job_id', 'ae_results.id']),
    UniqueConstraint('owner_id', 'job_id', 'cycle', name='uq_ae_reviews_job_cycle'),
    CheckConstraint("decision IN ('APPROVED','REJECTED','CORRECTION_REQUIRED')", name='decision'),
    CheckConstraint('cycle >= 0 AND cycle <= 2', name='review_cycle'))

deliveries = Table('ae_deliveries', metadata, *identity(),
    Column('job_id', String(36), nullable=False), Column('result_id', String(36), nullable=False),
    Column('state', String(32), nullable=False), Column('authorized_at', DateTime, nullable=False),
    Column('available_at', DateTime, nullable=False), Column('delivered_at', DateTime),
    Column('attempt_count', Integer, nullable=False, server_default='0'),
    Column('next_attempt_at', DateTime),
    ForeignKeyConstraint(['owner_id', 'job_id', 'result_id'], ['ae_results.owner_id', 'ae_results.job_id', 'ae_results.id']),
    UniqueConstraint('owner_id', 'job_id', 'result_id', name='uq_ae_deliveries_job_result'),
    CheckConstraint("state IN ('PENDING','DELIVERED','FAILED')", name='delivery_state'))

usage = Table('ae_usage', metadata, *identity(),
    Column('job_id', String(36), nullable=False), Column('provider_id', String(80), nullable=False),
    Column('provider_record_id', String(160)), Column('verified', Boolean, nullable=False),
    Column('evidence_source', String(40), nullable=False),
    Column('calls', Integer), Column('input_tokens', Integer), Column('output_tokens', Integer),
    Column('cost', Numeric(18, 8)), Column('currency', String(3)),
    Column('created_at', DateTime, nullable=False), tenant_ref('job_id', 'ae_jobs'),
    UniqueConstraint('owner_id', 'provider_id', 'provider_record_id', name='uq_ae_usage_provider_record'),
    CheckConstraint('(calls IS NULL OR calls >= 0) AND (input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0) AND (cost IS NULL OR cost >= 0)', name='usage_nonnegative'),
    CheckConstraint('(cost IS NULL AND currency IS NULL) OR (cost IS NOT NULL AND currency IS NOT NULL)', name='cost_currency'))

events = Table('ae_events', metadata, *identity(),
    Column('job_id', String(36), nullable=False), Column('sequence', Integer, nullable=False),
    Column('type', String(80), nullable=False), Column('actor_type', String(32), nullable=False),
    Column('actor_id', String(120), nullable=False), Column('reason_code', String(80)),
    Column('correlation_id', String(36), nullable=False), Column('created_at', DateTime, nullable=False),
    tenant_ref('job_id', 'ae_jobs'), UniqueConstraint('owner_id', 'job_id', 'sequence', name='uq_ae_events_job_sequence'))

outbox = Table('ae_outbox', metadata, *identity(),
    Column('job_id', String(36), nullable=False), Column('event_key', String(160), nullable=False),
    Column('capability', String(80), nullable=False), Column('task_id', String(36), nullable=False),
    Column('available_at', DateTime, nullable=False), Column('published_at', DateTime),
    Column('stream_message_id', String(80)), Column('attempt_count', Integer, nullable=False, server_default='0'),
    tenant_ref('job_id', 'ae_jobs'),
    ForeignKeyConstraint(['owner_id', 'job_id', 'task_id'], ['ae_tasks.owner_id', 'ae_tasks.job_id', 'ae_tasks.id']),
    UniqueConstraint('owner_id', 'event_key', name='uq_ae_outbox_event_key'), Index('ix_ae_outbox_due', 'published_at', 'available_at'))

workers = Table('ae_workers', metadata,
    Column('id', String(120), primary_key=True), Column('capabilities', JSON, nullable=False),
    Column('reported_state', String(24), nullable=False), Column('heartbeat_at', DateTime),
    Column('current_task_id', String(36), ForeignKey('ae_tasks.id')),
    CheckConstraint("reported_state IN ('AVAILABLE','BUSY')", name='worker_state'))

# Independent deletion audit; no FK to agents, users or clients that could later be removed.
agent_deletions = Table('ae_agent_deletions', metadata,
    Column('agent_id', String(36), primary_key=True), Column('owner_id', Integer, nullable=False),
    Column('legacy_agent_id', BigInteger), Column('operation_id', String(36), nullable=False),
    Column('actor_type', String(32), nullable=False), Column('actor_id', String(120), nullable=False),
    Column('interface', String(24), nullable=False), Column('deleted_at', DateTime, nullable=False),
    Column('snapshot', JSON, nullable=False),
    UniqueConstraint('owner_id', 'operation_id', name='uq_ae_deletion_owner_operation'),
    Index('ix_ae_deletion_owner_legacy', 'owner_id', 'legacy_agent_id'))

# Match the manually installed official DDL. This sets metadata only; no SQL runs.
for _table in metadata.tables.values():
    _table.dialect_options['mysql'].update(engine='InnoDB', charset='utf8mb4', collate='utf8mb4_0900_ai_ci')
