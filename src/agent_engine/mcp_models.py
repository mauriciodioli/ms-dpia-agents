"""Mappings verified with SHOW CREATE TABLE, 2026-11-12. No startup DDL."""
from sqlalchemy import MetaData, Table, Column, String, Text, Integer, SmallInteger, Boolean, DateTime, JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint
from .models import metadata as engine_metadata

# Independent metadata keeps these manually installed tables out of engine create_all.
metadata = MetaData()
servers = Table('ae_mcp_servers', metadata,
    Column('id', String(36), primary_key=True), Column('name', String(150), nullable=False),
    Column('description', Text), Column('connection_template', JSON), Column('endpoint_url', String(2048), nullable=False),
    Column('transport', String(32), nullable=False), Column('auth_type', String(32), nullable=False),
    Column('credential_ciphertext', Text), Column('enabled', Boolean, nullable=False),
    Column('priority', SmallInteger, nullable=False), Column('timeout_seconds', SmallInteger, nullable=False),
    Column('revision', Integer, nullable=False), Column('last_health_status', String(32), nullable=False),
    Column('last_error_code', String(80)), Column('last_checked_at', DateTime), Column('last_discovered_at', DateTime),
    Column('created_by', String(120), nullable=False), Column('updated_by', String(120)),
    Column('created_at', DateTime, nullable=False), Column('updated_at', DateTime, nullable=False), Column('deleted_at', DateTime))
tools = Table('ae_mcp_tools', metadata,
    Column('id', String(36), primary_key=True), Column('server_id', String(36), ForeignKey(servers.c.id), nullable=False),
    Column('tool_name', String(255), nullable=False), Column('description', Text), Column('input_schema', JSON),
    Column('enabled', Boolean, nullable=False), Column('risk_level', String(16), nullable=False), Column('capability', String(80)),
    Column('discovered_at', DateTime, nullable=False), Column('updated_at', DateTime, nullable=False))
grants = Table('ae_mcp_tool_grants', metadata,
    Column('owner_id', Integer, primary_key=True), Column('agent_id', String(36), primary_key=True),
    Column('tool_id', String(36), ForeignKey(tools.c.id), primary_key=True), Column('enabled', Boolean, nullable=False),
    Column('granted_by', String(120), nullable=False), Column('created_at', DateTime, nullable=False), Column('updated_at', DateTime, nullable=False),
    ForeignKeyConstraint(['owner_id','agent_id'],[engine_metadata.tables['ae_agents'].c.owner_id,engine_metadata.tables['ae_agents'].c.id]))
executions = Table('ae_mcp_executions', metadata,
    Column('id', String(36), primary_key=True), Column('owner_id', Integer, nullable=False), Column('agent_id', String(36), nullable=False),
    Column('job_id', String(36), nullable=False), Column('tool_id', String(36), ForeignKey(tools.c.id), nullable=False),
    Column('server_revision', Integer, nullable=False), Column('status', String(24), nullable=False), Column('duration_ms', Integer),
    Column('error_code', String(80)), Column('started_at', DateTime, nullable=False), Column('finished_at', DateTime),
    ForeignKeyConstraint(['owner_id','agent_id'],[engine_metadata.tables['ae_agents'].c.owner_id,engine_metadata.tables['ae_agents'].c.id]),
    ForeignKeyConstraint(['owner_id','job_id'],[engine_metadata.tables['ae_jobs'].c.owner_id,engine_metadata.tables['ae_jobs'].c.id]))
audit = Table('ae_mcp_audit', metadata,
    Column('id', String(36), primary_key=True), Column('server_id', String(36), ForeignKey(servers.c.id), nullable=False),
    Column('tool_id', String(36), ForeignKey(tools.c.id)), Column('actor_id', String(120), nullable=False),
    Column('action', String(48), nullable=False), Column('reason_code', String(80)), Column('details', JSON), Column('created_at', DateTime, nullable=False))

# Match the manually installed constraints and MySQL unsigned/time precision.
from sqlalchemy.dialects.mysql import INTEGER, SMALLINT, DATETIME
tools.append_constraint(UniqueConstraint('server_id','tool_name',name='uq_ae_mcp_tools_server_name'))
servers.append_constraint(CheckConstraint("transport = 'streamable_http'",name='ck_ae_mcp_servers_transport'))
servers.append_constraint(CheckConstraint("auth_type IN ('none','bearer','header')",name='ck_ae_mcp_servers_auth'))
servers.append_constraint(CheckConstraint('revision >= 1',name='ck_ae_mcp_servers_revision'))
servers.append_constraint(CheckConstraint('timeout_seconds BETWEEN 1 AND 120',name='ck_ae_mcp_servers_timeout'))
tools.append_constraint(CheckConstraint("risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",name='ck_ae_mcp_tools_risk'))
executions.append_constraint(CheckConstraint("status IN ('STARTED','SUCCEEDED','FAILED','CANCELLED','TIMED_OUT')",name='ck_ae_mcp_exec_status'))
for table in metadata.tables.values():
    table.dialect_options['mysql'].update(engine='InnoDB',charset='utf8mb4',collate='utf8mb4_0900_ai_ci')
    for column in table.c:
        if isinstance(column.type,DateTime):column.type=DateTime().with_variant(DATETIME(fsp=6),'mysql')
servers.c.revision.type=Integer().with_variant(INTEGER(unsigned=True),'mysql')
servers.c.timeout_seconds.type=SmallInteger().with_variant(SMALLINT(unsigned=True),'mysql')
executions.c.server_revision.type=Integer().with_variant(INTEGER(unsigned=True),'mysql')
executions.c.duration_ms.type=Integer().with_variant(INTEGER(unsigned=True),'mysql')
