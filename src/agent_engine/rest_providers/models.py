"""Independent additive storage. Never created on application startup."""
from sqlalchemy import MetaData,Table,Column,String,Integer,Boolean,Text,DateTime,Index
metadata=MetaData()
providers=Table('ae_rest_providers',metadata,
 Column('id',String(36),primary_key=True),Column('owner_id',Integer,nullable=False),
 Column('adapter',String(40),nullable=False),Column('name',String(150),nullable=False),Column('description',Text,nullable=False),
 Column('base_url',String(2048),nullable=False),Column('auth_type',String(30),nullable=False),Column('auth_header',String(80),nullable=False),
 Column('credential_ciphertext',Text),Column('credential_origin',String(255)),Column('enabled',Boolean,nullable=False),
 Column('timeout_seconds',Integer,nullable=False),Column('revision',Integer,nullable=False),
 Column('health',String(20),nullable=False),Column('error_code',String(80)),Column('http_status',Integer),
 Column('checked_at',DateTime),Column('created_at',DateTime,nullable=False),Column('updated_at',DateTime,nullable=False),
 Index('ix_ae_rest_providers_owner','owner_id','id'))
