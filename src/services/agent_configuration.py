"""Validated, inactive agent configuration. No scheduler, credits or provider execution."""
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import (MetaData, Table, Column, Integer, String, Boolean, DateTime,
                        JSON, Time, select, insert, update, UniqueConstraint)
from flask import current_app
from werkzeug.datastructures import MultiDict
from model.usuario import Usuario
from model.codigoPostal import CodigoPostal
from services.locations import postal_ids_for_city
from services.dpia_client import DPIAClient, catalog_filters
from services.query_preparation import PreparationError, COUNTRIES
from utils.db import db
from services.task_names import task_name
from services.task_name_backfill import fill_missing_v1_names

# Independent metadata: importing these tables never creates them through db.create_all().
metadata = MetaData()
agentes = Table('agentes', metadata,
    Column('id', Integer, primary_key=True), Column('usuario_id', Integer, nullable=False),
    Column('nombre', String(120)), Column('estado', String(20)), Column('idioma', String(10)),
    Column('pais_codigo', String(2)), Column('ciudad', String(150)), Column('zona_horaria', String(64)),
    Column('presupuesto_puntos_periodo', Integer), Column('periodo_presupuesto', String(10)),
    Column('notificaciones_activas', Boolean), Column('configuracion', JSON),
    Column('version_config', Integer), Column('creado_en', DateTime), Column('actualizado_en', DateTime),
    Column('activado_en', DateTime), UniqueConstraint('usuario_id'))
tareas = Table('agente_tareas', metadata,
    Column('id', Integer, primary_key=True), Column('agente_id', Integer, nullable=False),
    Column('tipo', String(30)), Column('nombre', String(150)), Column('habilitada', Boolean),
    Column('parametros', JSON), Column('ultima_ejecucion_en', DateTime),
    Column('creado_en', DateTime), Column('actualizado_en', DateTime),
    UniqueConstraint('agente_id', 'tipo'))
programaciones = Table('agente_programaciones', metadata,
    Column('id', Integer, primary_key=True), Column('agente_id', Integer, nullable=False),
    Column('activa', Boolean), Column('frecuencia', String(20)), Column('dias_semana', JSON),
    Column('hora_local', Time), Column('zona_horaria', String(64)),
    Column('proxima_ejecucion_en', DateTime), Column('ultima_ejecucion_en', DateTime),
    Column('creado_en', DateTime), Column('actualizado_en', DateTime), UniqueConstraint('agente_id'))
TASKS = {'products':'PRODUCTOS_NUEVOS', 'prices':'PRECIOS', 'suppliers':'PROVEEDORES',
         'local':'OPORTUNIDADES_LOCALES', 'jobs':'EMPLEOS', 'trends':'TENDENCIAS'}
FREQUENCIES = {'daily':'DIARIA', 'twice':'DOS_POR_SEMANA', 'weekly':'SEMANAL'}
PERIODS = {'week':'SEMANA', 'month':'MES'}
FIELDS = {'version','tasks','country','city','scopes','categories','frequency','days','time',
          'timezone','points','period','notifications','language'}


def bad(message='Revisá la configuración del agente.', status=400):
    raise PreparationError(message, status)


def positive_ids(value):
    return (isinstance(value,list) and 1 <= len(value) <= 500
            and all(type(v) is int and 1 <= v <= 2147483647 for v in value)
            and len(set(value)) == len(value))


def validate_config(data):
    """Validate before network calls or opening the write transaction. Client labels are not trusted."""
    if not isinstance(data,dict) or set(data) != FIELDS or type(data['version']) is not int or data['version'] != 1:
        bad()
    if not isinstance(data['tasks'],list) or not 1<=len(data['tasks'])<=len(TASKS) or any(not isinstance(t,str) or t not in TASKS for t in data['tasks']) or len(set(data['tasks']))!=len(data['tasks']):
        bad('Seleccioná al menos una tarea.')
    if not isinstance(data['country'],str) or data['country'] not in COUNTRIES or not isinstance(data['city'],str) or not 1<=len(data['city'].strip())<=100:
        bad('Elegí ubicación, ámbitos y categorías disponibles.')
    if not positive_ids(data['scopes']) or not positive_ids(data['categories']):
        bad('Elegí ubicación, ámbitos y categorías disponibles.')
    frequency=data['frequency'];days=data['days']
    if not isinstance(frequency,str) or frequency not in FREQUENCIES or not isinstance(days,list) or len(days)>7 or any(type(d) is not int or not 0<=d<=6 for d in days) or len(set(days))!=len(days):
        bad('Revisá el horario y los días seleccionados.')
    if frequency!='daily' and len(days)!=(2 if frequency=='twice' else 1):
        bad('Revisá el horario y los días seleccionados.')
    if not isinstance(data['time'],str) or len(data['time'])!=5 or data['time'][2]!=':':
        bad('Revisá el horario y los días seleccionados.')
    try:
        hour,minute=data['time'].split(':')
        if not hour.isdecimal() or not minute.isdecimal():bad()
        time(int(hour),int(minute))
        if not isinstance(data['timezone'],str) or not 1<=len(data['timezone'])<=64:bad()
        ZoneInfo(data['timezone'])
    except (ValueError,ZoneInfoNotFoundError):
        bad('Revisá el horario y los días seleccionados.')
    if type(data['points']) is not int or not 0<=data['points']<=1000000 or not isinstance(data['period'],str) or data['period'] not in PERIODS:
        bad('Ingresá un límite de puntos entero y no negativo.')
    if type(data['notifications']) is not bool or not isinstance(data['language'],str) or data['language'] not in ('es','en','pl','it'):
        bad()
    return {**data,'city':data['city'].strip(),'tasks':sorted(data['tasks']),
            'scopes':sorted(data['scopes']),'categories':sorted(data['categories']),
            'days':[] if frequency=='daily' else sorted(days)}


def verify_catalog(config):
    """Use the existing read-only catalog contract and postal associations, never paid providers."""
    ids=postal_ids_for_city(config['country'],config['city'])
    if not ids:bad('Elegí ubicación, ámbitos y categorías disponibles.')
    postal=db.session.get(CodigoPostal,ids[0])
    params=catalog_filters(MultiDict({'idioma':config['language']}),'ambitos')
    client=DPIAClient(current_app.config.get('SCRAPEADOR_SERVICE_KEY',''),timeout=(3.05,10))
    def fetch(task):
        name,postal_id=task
        return name,client.catalog(name,{**params,'codigo_postal_id':postal_id})[name]
    available_scopes={};available_categories={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name,rows in pool.map(fetch,[(name,postal_id) for postal_id in ids for name in ('ambitos','categorias')]):
            for row in rows:
                if name=='ambitos':available_scopes[row['ambito_id']]=row
                elif row['categoria_id'] in available_categories:
                    old=available_categories[row['categoria_id']]
                    old['ambito_ids']=sorted(set(old['ambito_ids']+row['ambito_ids']))
                else:available_categories[row['categoria_id']]=dict(row)
    if any(v not in available_scopes for v in config['scopes']) or any(v not in available_categories or not set(available_categories[v]['ambito_ids']).intersection(config['scopes']) for v in config['categories']):
        bad('Elegí ubicación, ámbitos y categorías disponibles.')
    if postal is None:bad('Elegí ubicación, ámbitos y categorías disponibles.')
    return {**config,'city':postal.ciudad.strip(),'scopeLabels':[{'id':i,'name':available_scopes[i]['nombre']} for i in config['scopes']],
            'categoryLabels':[{'id':i,'name':available_categories[i]['nombre']} for i in config['categories']]}


class AgentConfigurationStore:
    def _engine(self):
        if db.engine.dialect.name!='mysql':
            bad('El guardado del agente requiere MySQL.',503)
        return db.engine

    @staticmethod
    def _user(conn,user_id,lock=False):
        stmt=select(Usuario.id).where(Usuario.id==user_id,Usuario.activo.is_(True))
        if lock:stmt=stmt.with_for_update()
        if conn.execute(stmt).first() is None:bad('Iniciá sesión para guardar tu agente.',401)

    @staticmethod
    def _existing(conn,user_id):
        rows=conn.execute(select(agentes).where(agentes.c.usuario_id==user_id).limit(2)).mappings().all()
        if len(rows)>1:bad('Hay varias configuraciones para esta cuenta. Revisá los datos antes de guardar.',409)
        return rows[0] if rows else None

    @staticmethod
    def _serialize(conn,row):
        config=row['configuracion']
        if not isinstance(config,dict) or config.get('version')!=1:
            bad('La configuración guardada no es compatible. Revisala antes de guardar.',409)
        try:
            validate_config({key:config[key] for key in FIELDS})
        except (KeyError,PreparationError):
            bad('La configuración guardada no es compatible. Revisala antes de guardar.',409)
        enabled=conn.execute(select(tareas.c.tipo).where(tareas.c.agente_id==row['id'],tareas.c.habilitada.is_(True))).scalars().all()
        schedules=conn.execute(select(programaciones).where(programaciones.c.agente_id==row['id'])).mappings().all()
        if len(schedules)!=1 or len(enabled)!=len(set(enabled)) or set(enabled)!={TASKS[t] for t in config.get('tasks',[]) if t in TASKS}:
            bad('La configuración guardada no es compatible. Revisala antes de guardar.',409)
        # Refuse inconsistent/live configurations instead of presenting them as inactive.
        if row['estado'] not in ('BORRADOR','INACTIVO') or schedules[0]['activa']:
            bad('Este agente tiene actividad habilitada. No se modificó su configuración.',409)
        schedule=schedules[0]
        iso_days=list(range(1,8)) if config['frequency']=='daily' else sorted(day or 7 for day in config['days'])
        if (row['idioma']!=config['language'] or row['pais_codigo']!=COUNTRIES[config['country']][0]
                or row['ciudad']!=config['city'] or row['zona_horaria']!=config['timezone']
                or row['presupuesto_puntos_periodo']!=config['points'] or row['periodo_presupuesto']!=PERIODS[config['period']]
                or row['notificaciones_activas']!=config['notifications']
                or schedule['frecuencia']!=FREQUENCIES[config['frequency']] or schedule['dias_semana']!=iso_days
                or schedule['hora_local']!=time.fromisoformat(config['time']) or schedule['zona_horaria']!=config['timezone']
                or schedule['proxima_ejecucion_en'] is not None or type(row['version_config']) is not int or row['version_config']<1):
            bad('La configuración guardada no es compatible. Revisala antes de guardar.',409)
        return {'id':row['id'],'revision':row['version_config'],'state':'inactive','configuration':config}

    def get(self,user_id):
        with self._engine().begin() as conn:
            # A common user lock serializes reads and writes, including first creation.
            self._user(conn,user_id,lock=True)
            row=self._existing(conn,user_id)
            return self._serialize(conn,row) if row else None

    def save(self,user_id,config,expected_revision):
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        with self._engine().begin() as conn:
            self._user(conn,user_id,lock=True)
            previous=self._existing(conn,user_id)
            if previous:
                stored=self._serialize(conn,previous)
                # A retry after an uncertain response returns the confirmed same configuration.
                if previous['configuracion']==config:
                    fill_missing_v1_names(conn,tareas,previous['id'],previous['ciudad'] or '')
                    return stored
                if previous['version_config']!=expected_revision:
                    bad('La configuración cambió en otra pestaña. Volvé a cargarla antes de editar.',409)
            elif expected_revision!=0:
                bad('La configuración cambió en otra pestaña. Volvé a cargarla antes de editar.',409)
            if previous:
                fill_missing_v1_names(conn,tareas,previous['id'],previous['ciudad'] or '')
            values=dict(estado='INACTIVO',idioma=config['language'],pais_codigo=COUNTRIES[config['country']][0],
                        ciudad=config['city'],zona_horaria=config['timezone'],
                        presupuesto_puntos_periodo=config['points'],periodo_presupuesto=PERIODS[config['period']],
                        notificaciones_activas=config['notifications'],configuracion=config,
                        actualizado_en=now,activado_en=None)
            revision=previous['version_config']+1 if previous else 1
            values['version_config']=revision
            if previous:
                agent_id=previous['id'];conn.execute(update(agentes).where(agentes.c.id==agent_id,agentes.c.usuario_id==user_id).values(**values))
            else:
                agent_id=conn.execute(insert(agentes).values(usuario_id=user_id,nombre='Mi agente',creado_en=now,**values)).inserted_primary_key[0]
            task_rows=conn.execute(select(tareas).where(tareas.c.agente_id==agent_id)).mappings().all()
            current={row['tipo']:row for row in task_rows}
            if len(current)!=len(task_rows):bad('La configuración guardada no es compatible. Revisala antes de guardar.',409)
            desired={TASKS[t] for t in config['tasks']}
            for kind,row in current.items():
                if kind not in desired:conn.execute(update(tareas).where(tareas.c.id==row['id']).values(habilitada=False,actualizado_en=now))
            for kind in sorted(desired):
                fields=dict(habilitada=True,parametros={'schema_version':1,'scope_ids':config['scopes'],'category_ids':config['categories']},actualizado_en=now)
                if kind in current:
                    # Keep independent task editor settings when saving agent defaults.
                    previous_params=current[kind]['parametros'] or {}
                    fields['parametros'].update({key:previous_params[key] for key in
                        ('_agent_configuration','_configuration_revision') if key in previous_params})
                    conn.execute(update(tareas).where(tareas.c.id==current[kind]['id']).values(**fields))
                else:conn.execute(insert(tareas).values(agente_id=agent_id,tipo=kind,
                    nombre=task_name(kind.replace('_', ' ').lower(), city=config['city']),creado_en=now,**fields))
            schedule=conn.execute(select(programaciones.c.id).where(programaciones.c.agente_id==agent_id)).first()
            fields=dict(activa=False,frecuencia=FREQUENCIES[config['frequency']],
                        dias_semana=list(range(1,8)) if config['frequency']=='daily' else sorted(day or 7 for day in config['days']),
                        hora_local=time.fromisoformat(config['time']),zona_horaria=config['timezone'],
                        proxima_ejecucion_en=None,actualizado_en=now)
            if schedule:conn.execute(update(programaciones).where(programaciones.c.id==schedule.id).values(**fields))
            else:conn.execute(insert(programaciones).values(agente_id=agent_id,creado_en=now,**fields))
            return {'id':agent_id,'revision':revision,'state':'inactive','configuration':config}
