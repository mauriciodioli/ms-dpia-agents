"""Global administrative provider settings. Manual DDL; no startup migrations."""
from sqlalchemy import MetaData, Table, Column, String, Integer, Boolean, DateTime, JSON, Text

metadata = MetaData()
integrations = Table('ae_integrations', metadata,
    Column('id', String(40), primary_key=True),
    Column('config', JSON, nullable=False),
    Column('credential_ciphertext', Text),
    Column('enabled', Boolean, nullable=False, default=False),
    Column('revision', Integer, nullable=False),
    Column('diagnostic', JSON, nullable=False),
    Column('checked_at', DateTime),
    Column('last_success_at', DateTime),
    Column('updated_at', DateTime, nullable=False))

audit = Table('ae_integration_audit', metadata,
    Column('id', String(36), primary_key=True),
    Column('integration_id', String(40), nullable=False),
    Column('actor_id', String(120), nullable=False),
    Column('action', String(40), nullable=False),
    Column('revision', Integer, nullable=False),
    Column('reason_code', String(80)),
    Column('created_at', DateTime, nullable=False))

for table in metadata.tables.values():
    table.dialect_options['mysql'].update(engine='InnoDB', charset='utf8mb4', collate='utf8mb4_0900_ai_ci')
