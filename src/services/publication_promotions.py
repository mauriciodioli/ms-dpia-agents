"""Promotions debit the existing shared scraping point ledger atomically."""
import json
import hashlib
from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy import Table, Column, MetaData, Integer, String, DateTime, select, update, func
from werkzeug.exceptions import BadRequest, Conflict, NotFound, HTTPException, ServiceUnavailable
from model.publicaciones.publicaciones import Publicacion
from utils.db import db
from services.scraping_quota import MySQLScrapingQuota, operaciones, used_points

class PaymentRequired(HTTPException):
    code = 402


metadata = MetaData()
promotions = Table('pwa_publicacion_promociones', metadata,
    Column('promocion_id', String(36), primary_key=True), Column('usuario_id', Integer),
    Column('publicacion_id', Integer), Column('puntos', Integer), Column('dias', Integer),
    Column('inicio_en', DateTime), Column('fin_en', DateTime))


def utcnow():
    return datetime.utcnow()


def serialize(row):
    return {'promocion_id': row['promocion_id'], 'publicacion_id': row['publicacion_id'],
            'puntos': row['puntos'], 'dias': row['dias'],
            'inicio_en': row['inicio_en'].isoformat()+'Z', 'fin_en': row['fin_en'].isoformat()+'Z'}


def summary(user_id):
    balance = MySQLScrapingQuota().credits(user_id)['available']
    now = utcnow()
    rows = db.session.execute(select(promotions).where(promotions.c.usuario_id==user_id,
        promotions.c.inicio_en<=now, promotions.c.fin_en>now)).mappings().all()
    return {'saldo': balance or 0, 'costo': 5, 'dias': 5, 'promociones': [serialize(row) for row in rows]}


def _engine():
    if db.engine.dialect.name!='mysql':
        raise ServiceUnavailable('Las promociones requieren MySQL.')
    return db.engine




def activate(publication_id, user_id, operation_id):
    try:
        operation_id = str(UUID(operation_id))
    except (ValueError, TypeError, AttributeError):
        raise BadRequest('Identificador de promoción inválido.') from None
    with _engine().begin() as conn:
        total = MySQLScrapingQuota()._lock(conn, user_id)
        balance = max(0, total-used_points(conn, user_id))
        previous = conn.execute(select(promotions).where(promotions.c.promocion_id==operation_id)).mappings().first()
        if previous:
            if previous['usuario_id']!=user_id or previous['publicacion_id']!=publication_id:
                raise Conflict('El identificador corresponde a otra promoción.')
            return {'success': True, 'saldo': balance, 'promocion': serialize(previous), 'reutilizada': True}
        if conn.execute(select(operaciones.c.operacion_id).where(operaciones.c.operacion_id==operation_id)).first():
            raise Conflict('El identificador corresponde a otra operación.')
        publication = conn.execute(select(Publicacion.__table__).where(Publicacion.id==publication_id).with_for_update()).mappings().first()
        if not publication or publication['user_id']!=user_id:
            raise NotFound('Publicación no encontrada.')
        if str(publication['estado']).strip().lower()!='activo':
            raise Conflict('Solo podés destacar publicaciones activas.')
        now = utcnow()
        existing = conn.execute(select(promotions.c.promocion_id).where(promotions.c.publicacion_id==publication_id,
            promotions.c.fin_en>now)).first()
        if existing:
            raise Conflict('Esta publicación ya tiene una promoción vigente.')
        if balance<5:
            raise PaymentRequired('Necesitás 5 puntos disponibles. No se descontó saldo.')
        row = dict(promocion_id=operation_id, usuario_id=user_id, publicacion_id=publication_id,
                   puntos=5, dias=5, inicio_en=now, fin_en=now+timedelta(days=5))
        conn.execute(promotions.insert().values(**row))
        context = {'mode':'promocion', 'publicacion_id':publication_id, 'puntos':5, 'dias':5}
        conn.execute(operaciones.insert().values(operacion_id=operation_id, usuario_id=user_id,
            solicitud_hash=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest(),
            origen='promocion', estado='consumed', contexto_json=json.dumps(context),
            resultado_json=json.dumps({'status':'complete','promocion':serialize(row)}),
            creado_en=now, actualizado_en=now))
        return {'success': True, 'saldo': balance-5, 'promocion': serialize(row), 'reutilizada': False}


def active_publication_ids(viewer_id=None):
    now = utcnow()
    query = select(promotions.c.publicacion_id).where(promotions.c.inicio_en<=now, promotions.c.fin_en>now)
    if viewer_id is not None:
        query = query.where(promotions.c.usuario_id!=viewer_id)
    return query
