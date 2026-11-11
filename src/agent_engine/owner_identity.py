"""Verified identity for linked agents; independent agents retain their chosen name."""
from sqlalchemy import select
from model.usuario import Usuario
from .errors import EngineError


def owner_email(conn,owner):
    email=conn.execute(select(Usuario.correo_electronico).where(Usuario.id==owner)).scalar_one_or_none()
    if not isinstance(email,str) or not email.strip() or len(email.strip())>120:
        raise EngineError('owner_email_unavailable',409)
    return email.strip()


def persist_linked_name(conn,row):
    if row['legacy_agent_id'] is None:return row
    from sqlalchemy import update
    from . import models as m
    email=owner_email(conn,row['owner_id'])
    if row['name']!=email:
        conn.execute(update(m.agents).where(m.agents.c.id==row['id'],m.agents.c.owner_id==row['owner_id']).values(name=email))
        return {**row,'name':email}
    return row
