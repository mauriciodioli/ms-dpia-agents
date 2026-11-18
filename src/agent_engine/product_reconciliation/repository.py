"""Actual legacy MySQL contract, reflected without DDL. Caller owns transaction."""
import json
from decimal import Decimal
from datetime import datetime
from sqlalchemy import MetaData,Table,select,insert,inspect
from ..errors import EngineError


def serial(value):
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,datetime):return value.isoformat()
    raise TypeError('unsupported_reconciliation_value')

def json_safe(value):return json.loads(json.dumps(value,default=serial,allow_nan=False))

class Repository:
    def __init__(self,conn,*,dry_run=False):
        self.conn=conn;self.dry_run=dry_run;schema=inspect(conn)
        if not all(schema.has_table(n) for n in ('agente_observaciones','agente_cambios')):raise EngineError('reconciliation_history_tables_missing',409)
        md=MetaData()
        self.observations=Table('agente_observaciones',md,autoload_with=conn,resolve_fks=False)
        self.changes=Table('agente_cambios',md,autoload_with=conn,resolve_fks=False)
        required={'id','agente_id','ejecucion_tarea_id','tipo','fuente','referencia_externa','clave_entidad','titulo','url','precio','moneda','vendedor','ubicacion','datos','observado_en'}
        if not required<=set(self.observations.c.keys()) or not {'id','agente_id','observacion_anterior_id','observacion_actual_id','tipo','detalle','detectado_en'}<=set(self.changes.c.keys()):
            raise EngineError('reconciliation_schema_mismatch',409)
    def existing(self,agent,job,key):
        t=self.observations
        return self.conn.execute(select(t).where(t.c.agente_id==agent,t.c.clave_entidad==key,
            t.c.datos['reconciliation']['job_id'].as_string()==job).with_for_update(read=self.dry_run)).mappings().first()
    def latest(self,agent,key,at):
        t=self.observations
        row=self.conn.execute(select(t).where(t.c.agente_id==agent,t.c.clave_entidad==key,
            t.c.tipo=='PRODUCTO',t.c.observado_en<=at).order_by(t.c.observado_en.desc(),t.c.id.desc()).limit(1).with_for_update(read=self.dry_run)).mappings().first()
        if row:return row,dict(title=row['titulo'],price=row['precio'],currency=row['moneda'],seller=row['vendedor'],location=row['ubicacion'],url=row['url'])
        # Older observations can use a previous hash algorithm. Rebuild their
        # commercial identity, never match on title or cross agent boundaries.
        from .normalizer import normalize
        query=select(t).where(t.c.agente_id==agent,t.c.tipo=='PRODUCTO',t.c.observado_en<=at).order_by(t.c.observado_en.desc(),t.c.id.desc())
        for row in self.conn.execute(query).mappings():
            data={'items':[dict(title=row['titulo'],price=row['precio'],currency=row['moneda'],seller=row['vendedor'],location=row['ubicacion'],url=row['url'],marketplace=row['fuente'],product_id=row['referencia_externa'])]}
            products,_=normalize(data,job_id=None,observed_at=row['observado_en'],source='agente_observaciones')
            if products and products[0]['offer_key']==key:return row,products[0]
        return None,None
    def historical(self,owner,native_agent,legacy_agent,key,at):
        # Only explicitly owner/agent-linked rows are admissible as baselines.
        # Unlinked scraper history is deliberately never searched by title.
        from .normalizer import normalize
        best=None
        schema=inspect(self.conn)
        for name in ('scraper_trabajos','pwa_scraping_operaciones'):
            if not schema.has_table(name):continue
            table=Table(name,MetaData(),autoload_with=self.conn,resolve_fks=False)
            if 'usuario_id' not in table.c:continue
            payload_key=next((k for k in ('resultado_json','resultado','payload') if k in table.c),None)
            stamp_key=next((k for k in ('actualizado_en','creado_en','created_at') if k in table.c),None)
            if not payload_key or not stamp_key:continue
            query=select(table).where(table.c.usuario_id==owner,table.c[stamp_key]<=at).order_by(table.c[stamp_key].desc())
            for row in self.conn.execute(query).mappings():
                def decode(value):return json.loads(value) if isinstance(value,str) else value
                try:
                    context=decode(row.get('contexto_json')) or {}
                    linked=(row.get('agente_id')==legacy_agent or context.get('agent_id')==native_agent)
                    if not linked:continue
                    if 'estado' in row and row['estado'] not in ('consumed','COMPLETADO','COMPLETADA','completed','complete'):continue
                    products,_=normalize(decode(row[payload_key]),job_id=None,observed_at=row[stamp_key],source=name)
                except (TypeError,ValueError):continue
                for product in products:
                    if product['offer_key']==key and (best is None or product['observed_at']>best['observed_at']):best=product
        return best
    def legacy_execution(self,agent,job):
        if not inspect(self.conn).has_table('agente_ejecucion_tareas'):return None
        md=MetaData();t=Table('agente_ejecucion_tareas',md,autoload_with=self.conn,resolve_fks=False)
        if not {'id','ae_job_id'}<=set(t.c.keys()):return None
        rows=self.conn.execute(select(t.c.id).where(t.c.ae_job_id==job)).scalars().all()
        if len(rows)>1:raise EngineError('reconciliation_ambiguous_legacy_execution',409)
        return rows[0] if rows else None
    def store(self,agent,job,product,kind,details,previous_id,execution_id):
        stored={**json_safe(product),'reconciliation':{'version':1,'job_id':job,'kind':kind,'details':json_safe(details)}}
        result=self.conn.execute(insert(self.observations).values(agente_id=agent,ejecucion_tarea_id=execution_id,tipo='PRODUCTO',
            fuente=product['marketplace'] or product['source'],referencia_externa=product['external_id'],clave_entidad=product['offer_key'],
            titulo=product['title'],url=product['url'],precio=product['price'],moneda=product['currency'],vendedor=product['seller'],ubicacion=product['location'],
            datos=stored,observado_en=product['observed_at']))
        oid=result.inserted_primary_key[0]
        if kind!='SIN_CAMBIOS':self.conn.execute(insert(self.changes).values(agente_id=agent,observacion_anterior_id=previous_id,
            observacion_actual_id=oid,tipo=kind,detalle=json_safe(details),detectado_en=product['observed_at']))
