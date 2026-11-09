"""Transactional MySQL repository for the two manually provisioned PWA tables.

Separate metadata deliberately prevents db.create_all() from provisioning them.
"""
import hashlib
import json
from datetime import datetime, timezone
from model.usuario import Usuario
from sqlalchemy import Table, Column, MetaData, Integer, String, Text, DateTime, select, func, update, case
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import IntegrityError
from services.query_preparation import PreparationError
from utils.db import db

metadata = MetaData()
cupos = Table('pwa_scraping_cupos', metadata,
    Column('usuario_id', Integer, primary_key=True),
    Column('ejecuciones_habilitadas', Integer, nullable=False))
operaciones = Table('pwa_scraping_operaciones', metadata,
    Column('operacion_id', String(36), primary_key=True), Column('usuario_id', Integer),
    Column('solicitud_hash', String(64)), Column('origen', String(20)),
    Column('estado', String(20)), Column('contexto_json', Text), Column('resultado_json', Text),
    Column('proveedor_trabajo_id', String(160)), Column('creado_en', DateTime),
    Column('actualizado_en', DateTime))
HELD = ('reserved', 'dispatching', 'pending', 'consumed')
POINT_COST = case((operaciones.c.origen == 'promocion', 5), (operaciones.c.origen == 'recarga', 0), else_=1)

def self_topup_allowed(user_id):
    user=db.session.get(Usuario,user_id)
    return bool(user and user.activo and privileged_credit_role(user.roll))

def privileged_credit_role(role):
    return str(role or '').strip().casefold() in {'administrador','admin','avanzado','advanced'}


def used_points(conn, user_id):
    return int(conn.execute(select(func.coalesce(func.sum(POINT_COST), 0)).where(
        operaciones.c.usuario_id == user_id, operaciones.c.estado.in_(HELD))).scalar_one())


TRANSITIONS = {'reserved': {'dispatching', 'released'},
               'dispatching': {'consumed', 'pending', 'released'},
               'pending': {'consumed', 'released'}}


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def fingerprint(prepared):
    payload = {**prepared, 'context': {k: v for k, v in prepared['context'].items() if k != 'fecha'}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class MySQLScrapingQuota:
    def _engine(self):
        if db.engine.dialect.name != 'mysql':
            raise PreparationError('El contador requiere MySQL.', 503)
        return db.engine

    def _lock(self, conn, user_id):
        stmt = insert(cupos).values(usuario_id=user_id, ejecuciones_habilitadas=6)
        conn.execute(stmt.on_duplicate_key_update(usuario_id=stmt.inserted.usuario_id))
        return conn.execute(select(cupos.c.ejecuciones_habilitadas).where(
            cupos.c.usuario_id == user_id).with_for_update()).scalar_one()

    def reserve_direct(self, operation_id, user_id, prepared):
        digest = fingerprint(prepared)
        try:
            with self._engine().begin() as conn:
                total = self._lock(conn, user_id)
                existing = conn.execute(select(operaciones).where(
                    operaciones.c.operacion_id == operation_id).with_for_update()).mappings().first()
                if existing:
                    if existing['usuario_id'] != user_id or existing['solicitud_hash'] != digest:
                        raise PreparationError('El identificador pertenece a otro pedido.', 409)
                    return
                used = used_points(conn, user_id)
                if used >= total:
                    raise PreparationError('No quedan puntos disponibles.', 402)
                conn.execute(operaciones.insert().values(operacion_id=operation_id, usuario_id=user_id,
                    solicitud_hash=digest, origen=prepared['sources'][0], estado='reserved',
                    contexto_json=json.dumps(prepared, ensure_ascii=False)))
        except IntegrityError:
            raise PreparationError('El identificador de operación ya está registrado.', 409) from None

    def operation(self, operation_id, user_id):
        with self._engine().connect() as conn:
            row = conn.execute(select(operaciones).where(operaciones.c.operacion_id == operation_id,
                operaciones.c.usuario_id == user_id)).mappings().first()
            if not row or row['origen'] in ('promocion','recarga'):
                return None
            outcome = decode(row['resultado_json'])
            return {'operation_id': row['operacion_id'], 'source': row['origen'], 'state': row['estado'],
                    'outcome': json.dumps(outcome) if outcome is not None else None,
                    'prepared': decode(row['contexto_json'])}

    def transition(self, operation_id, user_id, state, payload=None):
        with self._engine().begin() as conn:
            self._lock(conn, user_id)
            row = conn.execute(select(operaciones.c.estado).where(
                operaciones.c.operacion_id == operation_id, operaciones.c.usuario_id == user_id
            ).with_for_update()).first()
            if not row or state not in TRANSITIONS.get(row[0], set()):
                return False
            values = {'estado': state}
            if payload is not None:
                values['resultado_json'] = json.dumps(payload, ensure_ascii=False)
                values['proveedor_trabajo_id'] = payload.get('provider_job_id')
            conn.execute(update(operaciones).where(operaciones.c.operacion_id == operation_id,
                operaciones.c.usuario_id == user_id).values(**values))
            return True

    def credits(self, user_id):
        with self._engine().begin() as conn:
            total = self._lock(conn, user_id)
            counts = dict(conn.execute(select(operaciones.c.estado, func.sum(POINT_COST)).where(
                operaciones.c.usuario_id == user_id).group_by(operaciones.c.estado)).all())
            rows = conn.execute(select(operaciones.c.operacion_id, operaciones.c.origen, operaciones.c.estado,
                case((operaciones.c.origen=='recarga',operaciones.c.resultado_json),else_=None)
                ).where(operaciones.c.usuario_id == user_id).order_by(
                operaciones.c.creado_en.desc(), operaciones.c.operacion_id).limit(30)).all()
            reserved = sum(int(counts.get(state, 0)) for state in ('reserved', 'dispatching', 'pending'))
            consumed = int(counts.get('consumed', 0))
            return {'initial': total, 'available': max(0, total-reserved-consumed),
                    'reserved': reserved, 'consumed': consumed,
                    'operations': [{'operation_id': row[0], 'source': row[1], 'state': row[2], 'cost': 0 if row[1]=='recarga' else 5 if row[1]=='promocion' else 1,
                                    **({'amount':(decode(row[3]) or {}).get('credited_points',0)} if row[1]=='recarga' else {})} for row in rows]}

    def grant_points(self, user_id, amount, request_id):
        """Role-authorized self-credit, atomic and idempotent; uses existing tables only."""
        if type(amount) is not int or amount != 6:
            raise PreparationError('La recarga autorizada es de 6 puntos.',400)
        digest=hashlib.sha256(json.dumps({'user_id':user_id,'amount':amount,'action':'self_credit'},sort_keys=True).encode()).hexdigest()
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        with self._engine().begin() as conn:
            user=conn.execute(select(Usuario.activo,Usuario.roll).where(Usuario.id==user_id).with_for_update()).first()
            if not user or not user.activo:
                raise PreparationError('Iniciá sesión.',401)
            if not privileged_credit_role(user.roll):
                raise PreparationError('Solo administradores y usuarios avanzados pueden cargar puntos sin pago.',403)
            total=self._lock(conn,user_id)
            previous=conn.execute(select(operaciones).where(operaciones.c.operacion_id==request_id).with_for_update()).mappings().first()
            if previous:
                if previous['usuario_id']!=user_id or previous['origen']!='recarga' or previous['solicitud_hash']!=digest:
                    raise PreparationError('El identificador de recarga ya está utilizado.',409)
                return {'credited_points':amount,'reused':True}
            if total>2147483647-amount:
                raise PreparationError('La cantidad supera el límite del saldo.',400)
            conn.execute(update(cupos).where(cupos.c.usuario_id==user_id).values(ejecuciones_habilitadas=total+amount))
            # released means no hold or debit; source=recarga identifies the credit entry.
            conn.execute(operaciones.insert().values(operacion_id=request_id,usuario_id=user_id,
                origen='recarga',estado='released',solicitud_hash=digest,
                contexto_json=json.dumps({'action':'self_credit','actor_user_id':user_id,'amount':amount}),
                resultado_json=json.dumps({'credited_points':amount}),creado_en=now,actualizado_en=now))
            return {'credited_points':amount,'reused':False}

    def grant_test(self, user_id):
        with self._engine().begin() as conn:
            self._lock(conn, user_id)
            conn.execute(update(cupos).where(cupos.c.usuario_id == user_id).values(
                ejecuciones_habilitadas=cupos.c.ejecuciones_habilitadas+6))

    def history(self, user_id, offset=0):
        with self._engine().connect() as conn:
            rows = conn.execute(select(operaciones).where(operaciones.c.usuario_id == user_id, ~operaciones.c.origen.in_(('promocion','recarga')))
                .order_by(operaciones.c.creado_en.desc(), operaciones.c.operacion_id)
                .offset(offset).limit(25)).mappings().all()
            history = []
            for row in rows[:24]:
                prepared = decode(row['contexto_json']) or {}
                outcome = decode(row['resultado_json']) or {}
                context = prepared.get('context', {})
                history.append({'operation_id': row['operacion_id'], 'source': row['origen'],
                    'state': row['estado'], 'query': prepared.get('user_message', ''),
                    'city': context.get('ciudad', ''), 'category': context.get('categoria', ''),
                    'created_at': row['creado_en'].isoformat() if row['creado_en'] else None,
                    'product_count': len(outcome.get('products') or [])})
            return {'operations': history, 'has_more': len(rows)>24}

    def image_stage(self, operation_id, user_id, index, *, token=None, stage=None):
        """Claim once or save a gallery without changing the scraping allowance."""
        import uuid
        with self._engine().begin() as conn:
            self._lock(conn, user_id)
            row = conn.execute(select(operaciones).where(operaciones.c.operacion_id == operation_id,
                operaciones.c.usuario_id == user_id).with_for_update()).mappings().first()
            if not row:
                raise PreparationError('Operación no encontrada.', 404)
            if row['estado'] != 'consumed':
                raise PreparationError('El scraping todavía no tiene resultados confirmados.', 409)
            outcome = decode(row['resultado_json']) or {}
            if not 0 <= index < len(outcome.get('products') or []):
                raise PreparationError('Producto no encontrado.', 404)
            stages = outcome.setdefault('image_stages', {})
            previous = stages.get(str(index), {})
            if token is None:
                if previous.get('status') == 'complete':
                    return previous
                if previous.get('status') in ('loading', 'pending'):
                    raise PreparationError('Las imágenes están pendientes de confirmación. No se reenviará la solicitud.', 409)
                previous = {'status': 'loading', 'token': str(uuid.uuid4())}
                stages[str(index)] = previous
            else:
                if previous.get('token') != token:
                    raise PreparationError('La preparación de imágenes cambió.', 409)
                stages[str(index)] = stage
            conn.execute(update(operaciones).where(operaciones.c.operacion_id == operation_id,
                operaciones.c.usuario_id == user_id).values(resultado_json=json.dumps(outcome, ensure_ascii=False)))
            return stages[str(index)]

    def image_tasks(self, user_id=None):
        """Discover durable image jobs in existing JSON, including after a restart."""
        with self._engine().connect() as conn:
            query=select(operaciones).where(operaciones.c.origen=='amazon',
                operaciones.c.estado=='consumed',
                operaciones.c.resultado_json.like('%"queue_kind": "base44_images"%'))
            if user_id is not None:query=query.where(operaciones.c.usuario_id==user_id)
            rows=conn.execute(query).mappings().all()
            tasks=[]
            for row in rows:
                outcome=decode(row['resultado_json']) or {}
                for index,stage in outcome.get('image_stages',{}).items():
                    if stage.get('queue_kind')!='base44_images':continue
                    products=outcome.get('products') or []
                    if not str(index).isdigit() or int(index)>=len(products):continue
                    tasks.append(dict(operation_id=row['operacion_id'],user_id=row['usuario_id'],
                                      product_index=int(index),product=products[int(index)],stage=stage))
            return tasks

    def image_task(self, operation_id, user_id, index, *, initial=None, replace_legacy=None, claim=False, retry=False, token=None, changes=None, now=None):
        """Atomic queue/lease/CAS inside resultado_json; never changes point charges."""
        import time
        import uuid
        now=time.time() if now is None else now
        with self._engine().begin() as conn:
            self._lock(conn,user_id)
            row=conn.execute(select(operaciones).where(operaciones.c.operacion_id==operation_id,
                operaciones.c.usuario_id==user_id).with_for_update()).mappings().first()
            if not row:raise PreparationError('Operación no encontrada.',404)
            if row['origen']!='amazon' or row['estado']!='consumed':
                raise PreparationError('Se requiere una búsqueda Amazon confirmada.',409)
            outcome=decode(row['resultado_json']) or {}
            if type(index) is not int or not 0<=index<len(outcome.get('products') or []):
                raise PreparationError('Producto no encontrado.',404)
            stages=outcome.setdefault('image_stages',{});old=stages.get(str(index))
            if initial is not None:
                if old and not (replace_legacy is not None and old==replace_legacy and
                    old.get('queue_kind')!='base44_images' and old.get('status')!='complete'):
                    return old
                stage={**initial,'queue_kind':'base44_images','status':'pending',
                    'idempotency_key':'pwa-images:'+str(uuid.uuid4()),
                    'created_at':now,'updated_at':now,'next_check_at':0,'lease_until':0}
            elif retry:
                if not old or old.get('queue_kind')!='base44_images':return old
                if old.get('status')=='complete' or old.get('lease_until',0)>now:return old
                stage={**old,'retry_requested':True,'status':'pending','next_check_at':0,'updated_at':now}
            elif claim:
                if (not old or old.get('queue_kind')!='base44_images' or
                    old.get('status') not in ('pending','running') or
                    old.get('lease_until',0)>now or old.get('next_check_at',0)>now):return None
                stage={**old,'lease_token':str(uuid.uuid4()),'lease_until':now+240,'updated_at':now}
            elif changes is not None:
                if not old or old.get('lease_token')!=token:return None
                stage={**old,**changes,'updated_at':now}
            else:return old
            stages[str(index)]=stage
            conn.execute(update(operaciones).where(operaciones.c.operacion_id==operation_id,
                operaciones.c.usuario_id==user_id).values(resultado_json=json.dumps(outcome,ensure_ascii=False)))
            return stage

    def novel_generation(self, operation_id, user_id, *, token=None, result=None, error=None):
        """Durable OpenAI claim/result inside the existing reservation, without DDL."""
        import uuid
        with self._engine().begin() as conn:
            self._lock(conn,user_id)
            row=conn.execute(select(operaciones).where(operaciones.c.operacion_id==operation_id,
                operaciones.c.usuario_id==user_id).with_for_update()).mappings().first()
            if not row:raise PreparationError('Operación no encontrada.',404)
            outcome=decode(row['resultado_json']) or {}
            generation=outcome.get('generation',{})
            claiming=token is None
            if claiming:
                if outcome.get('generation_result'):
                    return {'result':outcome['generation_result']}
                if row['estado']!='reserved' or generation.get('status')=='running':
                    raise PreparationError('La consulta de novedades ya está en preparación. Consultá su estado.',409)
                token=str(uuid.uuid4())
                outcome={'status':'pending','products':[],'generation':{'status':'running','token':token}}
                state='reserved'
            else:
                if row['estado']!='reserved' or generation.get('token')!=token or generation.get('status')!='running':
                    raise PreparationError('La preparación ya fue procesada.',409)
                if error:
                    outcome={'status':'failed','error':error,'products':[],'generation':{'status':'failed'}}
                    state='released'
                else:
                    clarification=result['needs_clarification']
                    outcome={'status':'clarification_required' if clarification else 'pending','products':[],
                             'generation':{'status':'complete'},'generation_result':result}
                    state='released' if clarification else 'reserved'
            conn.execute(update(operaciones).where(operaciones.c.operacion_id==operation_id,
                operaciones.c.usuario_id==user_id).values(estado=state,resultado_json=json.dumps(outcome,ensure_ascii=False)))
            return {'token':token} if claiming else {'result':result}
