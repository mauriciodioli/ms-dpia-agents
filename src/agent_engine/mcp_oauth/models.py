"""Additive OAuth tables, independent metadata: never provisioned on import."""
from sqlalchemy import MetaData,Table,Column,String,Integer,Text,JSON,DateTime,Index,UniqueConstraint
metadata=MetaData()
connections=Table('ae_mcp_oauth_connections',metadata,
 Column('server_id',String(36),primary_key=True),Column('owner_id',Integer,primary_key=True),
 Column('resource_url',String(2048),nullable=False),Column('server_revision',Integer,nullable=False),
 Column('status',String(20),nullable=False),Column('metadata',JSON,nullable=False),
 Column('client_ciphertext',Text),Column('tokens_ciphertext',Text),Column('expires_at',DateTime),
 Column('active_flow',String(64)),Column('refresh_operation',String(64)),Column('error_code',String(80)),
 Column('updated_at',DateTime,nullable=False))
flows=Table('ae_mcp_oauth_flows',metadata,
 Column('state_hash',String(64),primary_key=True),Column('server_id',String(36),nullable=False),
 Column('owner_id',Integer,nullable=False),Column('session_hash',String(64),nullable=False),
 Column('code_hash',String(64)),UniqueConstraint('owner_id','server_id','code_hash',name='uq_ae_mcp_oauth_code'),
 Column('secret_ciphertext',Text),Column('expires_at',DateTime,nullable=False),Column('used_at',DateTime),
 Index('ix_ae_mcp_oauth_expiry','expires_at'))
