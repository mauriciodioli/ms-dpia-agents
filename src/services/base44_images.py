"""Base44 gallery adapter and recoverable worker over existing PWA operation JSON.

No scraper implementation, DDL, Sheets, OpenAI or remote publication writes.
"""
import json
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID
import requests
from services.dpia_client import DPIAClient
from services.query_preparation import PreparationError


def valid_uuid(value):
    try:return isinstance(value,str) and str(UUID(value))==value.lower()
    except (ValueError,TypeError,AttributeError):return False


def public_stage(stage):
    allowed=('status','images','error','filters','diagnostics','publication','created_at','updated_at')
    return {key:stage[key] for key in allowed if key in stage}


class Base44Images:
    def __init__(self,config):
        self.key=config.get('SCRAPEADOR_SERVICE_KEY','')
        if not self.key:raise PreparationError('Falta la conexión con DPIA.',503)
        self.headers={'Authorization':'Bearer '+self.key}

    def request(self,method,path,**kwargs):
        fn=requests.get if method=='GET' else requests.post
        try:
            with fn(DPIAClient.BASE_URL+path,headers=self.headers,timeout=(3.05,180 if method=='POST' else 15),
                    allow_redirects=False,**kwargs) as response:
                status=response.status_code
                if status!=200:
                    error=PreparationError('DPIA no confirmó la preparación de imágenes.',status if status in (400,401,403,404,409,410,415) else 502)
                    error.remote_busy=False
                    if status==409:
                        try:
                            body=response.json();reason=body.get('error') if isinstance(body,dict) else None
                            error.remote_busy=isinstance(reason,str) and ('ocupado' in reason.casefold() or 'en curso' in reason.casefold())
                        except (ValueError,TypeError):pass
                    error.remote_status=status
                    raise error
                data=response.json()
        except (requests.RequestException,ValueError):
            raise PreparationError('No se pudo confirmar el estado de las imágenes en DPIA.',502) from None
        if not isinstance(data,dict) or data.get('success') is not True:
            raise PreparationError('DPIA no confirmó la preparación de imágenes.',502)
        return data

    def job(self,job_id):
        if not valid_uuid(job_id):raise PreparationError('Falta la referencia del trabajo original de DPIA.',409)
        data=self.request('GET','/base44/trabajos/'+job_id)
        if data.get('trabajo_id')!=job_id or data.get('marketplace')!='amazon':
            raise PreparationError('El trabajo no corresponde a Amazon.',409)
        return data

    def authorize(self):
        self.request('GET','/auth/check',params={'permiso':'scraper:write'})


def product_reference(job,item):
    """Match stable original ASIN+host, never title or array position."""
    asin=item.get('asin')
    try:host=(urlsplit(item.get('url') or '').hostname or '').lower()
    except (ValueError,TypeError):host=''
    if not isinstance(asin,str) or not re.fullmatch(r'[A-Za-z0-9]{10}',asin) or host not in tuple(prefix+'amazon.'+domain for domain in ('com','ca','fr','it','de','es','pl') for prefix in ('','www.')):
        raise PreparationError('El producto no tiene ASIN y URL originales verificables.',409)
    matches=[]
    for product in job.get('productos') or []:
        if not isinstance(product,dict) or not valid_uuid(product.get('producto_id')):continue
        original=product.get('item') or {}
        if not isinstance(original,dict):continue
        try:other_host=(urlsplit(original.get('url') or '').hostname or '').lower()
        except (ValueError,TypeError):continue
        if original.get('asin')==asin and other_host==host:matches.append(product['producto_id'])
    if len(matches)!=1:
        raise PreparationError('No se pudo identificar de forma única el producto original en DPIA.',409)
    return matches[0]


def remote_gallery(job,product_id):
    """Map only confirmed per-product evidence, not a job-wide completion flag."""
    selected=job.get('seleccionados') or {}
    entry=selected.get(product_id) if isinstance(selected,dict) else None
    products=job.get('productos') or []
    if entry is None and isinstance(products,list):
        entry=next((p for p in products if isinstance(p,dict) and p.get('producto_id')==product_id and 'imagenes' in p),None)
    errors=[e for e in job.get('errores') or [] if isinstance(e,dict) and e.get('producto_id')==product_id]
    photos=[]
    if isinstance(entry,dict) and isinstance(entry.get('imagenes'),list):
        from services.query_execution import safe_product_url
        for value in entry['imagenes']:
            url=safe_product_url(value)
            if url and not urlsplit(url).password and url not in photos:photos.append(url)
        if photos:return {'status':'complete','images':photos[:6],**({'error':'DPIA devolvió una galería parcial.'} if errors else {})}
        return {'status':'failed','images':[],'error':'DPIA no devolvió imágenes válidas para el producto.'}
    if errors:
        filtered=any('filtro' in str(e.get('error','')).casefold() for e in errors)
        return {'status':'failed','images':[],'error':('La API descartó este producto por sus filtros propios, aunque haya superado los filtros de la PWA.' if filtered else 'DPIA informó un fallo en la preparación de este producto.')}
    return None


def process_image_task(app,task):
    """One durable claim; only an explicit button action authorizes resubmission."""
    from model.usuario import Usuario
    from utils.db import db
    quota=app.extensions['scraping_quota'];op=task['operation_id'];uid=task['user_id'];index=task['product_index']
    stage=quota.image_task(op,uid,index,claim=True)
    if not stage:return
    token=stage['lease_token']
    def save(changes):
        return quota.image_task(op,uid,index,token=token,changes=changes)
    def finish(changes):
        return save({**changes,'lease_until':0,'next_check_at':time.time()+10})
    try:
        user=db.session.get(Usuario,uid)
        if not user or not user.activo:
            finish({'status':'failed','images':[],'error':'La cuenta ya no está activa.'});return
        client=Base44Images(app.config)
        job=client.job(stage['trabajo_id'])
        found=remote_gallery(job,stage['producto_id'])
        if found:finish(found);return
        # A previous attempt may still run remotely. Never automatically repeat it.
        if stage.get('submitted_at') and not stage.get('retry_requested'):
            finish({'status':'pending','error':'Preparación pendiente de confirmación en DPIA. No se reenviará automáticamente.'});return
        if not any(p.get('producto_id')==stage['producto_id'] for p in job.get('productos',[]) if isinstance(p,dict)):
            finish({'status':'failed','images':[],'error':'El producto ya no pertenece al trabajo original.'});return
        client.authorize()
        # Persist the intent before POST; this survives a process/browser restart.
        if not save({'submitted_at':time.time(),'status':'pending','retry_requested':False}):return
        reply=client.request('POST','/base44/imagenes',json={'trabajo_id':stage['trabajo_id'],
            'productos':[{'producto_id':stage['producto_id']}],'idempotency_key':stage['idempotency_key']})
        if reply.get('trabajo_id')!=stage['trabajo_id']:
            finish({'status':'pending','error':'La respuesta de DPIA no identifica el trabajo esperado.'});return
        found=remote_gallery(reply,stage['producto_id'])
        finish(found or {'status':'pending','error':'DPIA todavía no confirmó imágenes para este producto.'})
    except PreparationError as exc:
        status=getattr(exc,'remote_status',None)
        if status in (400,401,403,404,410,415):
            finish({'status':'failed','images':[],'error':'DPIA rechazó la preparación o el trabajo ya no está disponible (HTTP '+str(status)+').'})
        elif status==409:
            try:
                found=remote_gallery(client.job(stage['trabajo_id']),stage['producto_id'])
            except PreparationError:
                found=None
            finish(found or {'status':'running' if getattr(exc,'remote_busy',False) else 'pending',
                'error':'DPIA informó un conflicto. Se consultará el estado del trabajo.'})
        else:finish({'status':'pending','error':str(exc)})
    except Exception:
        # No exception repr: DB/provider exceptions may embed credentials.
        finish({'status':'pending','error':'No se pudo confirmar la preparación. Se recuperará desde el estado guardado.'})


def start_image_worker(app):
    """The thread executes a DB-backed queue, never an in-memory task list.

    Leases are cross-process and expire; restart scans only explicitly queued stages.
    It never initiates new searches, legacy work, or retries uncertain paid POSTs.
    """
    if not app.config.get('LIVE_PROVIDER_CALLS_ENABLED') or app.config.get('TESTING'):return
    stop=threading.Event()
    def loop():
        while not stop.wait(5):
            try:
                with app.app_context():
                    quota=app.extensions['scraping_quota']
                    for task in quota.image_tasks():
                        if task['stage'].get('status') in ('pending','running'):process_image_task(app,task)
            except Exception:
                app.logger.warning('No se pudo revisar la cola persistente de imágenes; se volverá a consultar.')
    thread=threading.Thread(target=loop,name='dpia-persisted-images',daemon=True)
    app.extensions['image_worker_stop']=stop;thread.start()
