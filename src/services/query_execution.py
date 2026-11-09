"""Dispatch validated results to existing DPIA endpoints; internal sources stay local."""
import requests
import re
from sqlalchemy import or_, func
from model.publicaciones.publicaciones import Publicacion
from services.dpia_client import DPIAClient
from services.query_preparation import PreparationError
from services.query_sources import EXTERNAL, search_terms
from services.result_generation import sheet_rows

COUNTRY_KEYS={'Argentina':'argentina','Italia':'italia','España':'espana','Polonia':'polonia','México':'mexico','Uruguay':'uruguay'}


def internal_results(source,prepared):
    from services.local_publications import publications_for_city
    ctx=prepared['context'];cat=prepared['ids']['categoria_id'];terms=search_terms(prepared['user_message'])
    if source=='local':
        # Same existing postal scope, with keyword filtering before pagination.
        rows,_=publications_for_city(ctx['pais'],ctx['ciudad'],category_id=cat,terms=terms)
        return rows
    query=Publicacion.query.filter(func.lower(func.trim(Publicacion.estado))=='activo',Publicacion.categoria_id==cat)
    if terms:query=query.filter(or_(*(or_(Publicacion.titulo.ilike('%'+t+'%'),Publicacion.descripcion.ilike('%'+t+'%')) for t in terms)))
    rows=query.order_by(Publicacion.fecha_creacion.desc(),Publicacion.id.desc()).limit(24).all()
    return [dict(id=row.id,titulo=row.titulo,descripcion=row.descripcion,imagen=row.imagen,precio=row.precio,moneda=row.moneda) for row in rows]


def safe_product_url(value):
    from urllib.parse import urlsplit
    if not isinstance(value,str):return None
    try:
        parsed=urlsplit(value)
        return value if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username else None
    except ValueError:return None


def normalize_products(rows,source):
    products=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):continue
        items=row.get('items',[])
        if not isinstance(items,list):continue
        for item in items:
            if not isinstance(item,dict):continue
            title=item.get('titulo') or item.get('title') or item.get('name')
            if not isinstance(title,str) or not title.strip():continue
            url=safe_product_url(item.get('url') or item.get('link'))
            identity=url or title.strip().casefold()
            if identity in seen:continue
            seen.add(identity)
            price=item.get('precio',item.get('price'))
            if not isinstance(price,(str,int,float,dict)) or isinstance(price,bool):price=None
            products.append({'title':title.strip(),'price':price,'currency':item.get('moneda') or item.get('currency'),
                'image':safe_product_url(item.get('imagen') or item.get('image')),'url':url,'marketplace':source})
            if len(products)==20:return products
    return products


def dispatch_external(source,result,config,*,quota=None,operation_id=None,base44=False):
    import json
    if source not in EXTERNAL:raise PreparationError('Este origen no permite scraping externo.')
    user_id=result['context']['usuario']
    if quota is None or not operation_id:raise PreparationError('Se requiere una reserva de scraping.')
    execution=quota.operation(operation_id,user_id)
    if not execution or execution['source']!=source:raise PreparationError('Reserva de scraping inválida.',409)
    if execution['state']!='reserved':
        if execution.get('outcome'):return json.loads(execution['outcome'])
        return {'status':'pending','operation_id':operation_id,'error':'La ejecución ya fue enviada; no se reenviará.'}
    # Claim once before preflight so a concurrent retry cannot release a
    # reservation belonging to another request while it contacts the provider.
    if not quota.transition(operation_id,user_id,'dispatching'):
        return {'status':'pending','operation_id':operation_id,'error':'La ejecución ya fue enviada.'}
    generation=json.loads(execution['outcome']).get('generation_result') if execution.get('outcome') else None
    def finish(state,payload):
        if generation is not None:payload={**payload,'generation_result':generation}
        payload={**payload,'operation_id':operation_id}
        quota.transition(operation_id,user_id,state,payload)
        return payload
    def rejected(message):return finish('released',{'status':'failed','error':message,'products':[]})
    key=config.get('SCRAPEADOR_SERVICE_KEY','')
    if not config.get('LIVE_PROVIDER_CALLS_ENABLED',False):return rejected('Las llamadas reales están deshabilitadas.')
    if not key:return rejected('Falta SCRAPEADOR_SERVICE_KEY.')
    headers={'Authorization':f'Bearer {key}'}
    country=COUNTRY_KEYS.get(result['context']['pais'])
    # All failures here are known to occur before any scraping POST.
    try:
        with requests.get(DPIAClient.BASE_URL+'/auth/check',params={'permiso':'scraper:write'},
                          headers=headers,timeout=(3.05,10),allow_redirects=False) as response:
            if response.status_code!=200 or not response.json().get('success'):
                return rejected('El token no tiene permiso scraper:write.')
        with requests.get(DPIAClient.BASE_URL+'/marketplaces',headers=headers,timeout=(3.05,10),allow_redirects=False) as response:
            if response.status_code!=200:return rejected('No se pudieron verificar los marketplaces.')
            markets=response.json().get('datos',{})
        if country not in markets.get(source,{}).get('domains',{}):return rejected('El marketplace no admite el país seleccionado.')
    except (requests.RequestException,ValueError,TypeError,AttributeError):
        return rejected('No se pudo verificar el servicio antes de iniciar scraping.')
    plan=next((row for row in result['scrape_plan'] if row['source']==source),{})
    query=plan.get('search_query') or result['query'].get('normalized_intent') or result['query']['raw_user_message']
    if not isinstance(query,str) or not query.strip() or len(query)>500:return rejected('El plan no contiene una búsqueda válida.')
    ctx=result['context']
    # Exactly one keyword and one marketplace: no fan-out across generated candidates.
    payload={'pais_defecto':country,'registros':[{'Producto':query.strip(),'País':country,
        'usuario':user_id,'ambito':ctx['ambito'],'Categoría':ctx['categoria'],
        'codigoPostal':ctx['codigoPostal'],'idioma':ctx['idioma']}]}
    if source=='amazon':payload['batch_size']=1
    if base44:
        payload.update(marketplace='amazon',idempotency_key='pwa-search:'+operation_id)
    def uncertain(message,job_id=None):
        return finish('pending',{'status':'pending','error':message,'provider_job_id':job_id,'products':[]})
    try:
        with requests.post(DPIAClient.BASE_URL+('/base44/scraping' if base44 else '/scraping/'+source),headers=headers,json=payload,
                           timeout=(3.05,180),allow_redirects=False) as response:
            if response.status_code in (401,403,404,405):return rejected('El servicio rechazó la solicitud antes de iniciar scraping.')
            if response.status_code!=200:return uncertain('El servicio no confirmó si inició el scraping. La ejecución queda reservada.')
            data=response.json()
        if not isinstance(data,dict):return uncertain('No se pudo confirmar el resultado del scraping.')
        job_id=data.get('trabajo_id') or data.get('job_id')
        if job_id is not None:job_id=str(job_id)[:160]
        if not data.get('success') or not isinstance(data.get('datos'),list):
            return uncertain('Trabajo pendiente de confirmación; no se reenviará automáticamente.',job_id)
        def clean(value):
            if isinstance(value,dict):return {k:('El proveedor informó un fallo.' if k=='error' and v else clean(v)) for k,v in value.items() if k.lower() not in ('token','api_key','authorization','password','access_token','secret')}
            if isinstance(value,list):return [clean(v) for v in value]
            if isinstance(value,str):return re.sub(r'(?i)([?&](?:token|api_key|access_token)=)[^&\s]+',r'\1[REDACTADO]',value.replace(key,'[REDACTADO]'))
            return value
        rows=clean(data['datos']);products=normalize_products(rows,source)
        errors=any(isinstance(row,dict) and row.get('error') for row in rows)
        if errors and not products:return uncertain('El proveedor informó un fallo sin confirmar el inicio. Pendiente de revisión.',job_id)
        status='partial' if errors else 'complete' if products else 'empty'
        outcome={'status':status,'products':products,'data':rows,'provider_job_id':job_id}
        if base44:
            from services.base44_images import valid_uuid
            if valid_uuid(job_id):outcome['base44']={'trabajo_id':job_id}
            else:outcome['image_error']='DPIA no devolvió una referencia de trabajo válida; no se prepararán imágenes.'
        return finish('consumed',outcome)
    except requests.ConnectTimeout:
        return rejected('No se pudo establecer la conexión; el scraping no comenzó.')
    except (requests.RequestException,ValueError,TypeError,AttributeError):
        return uncertain('Se perdió la confirmación del scraping. La ejecución queda pendiente y no se reenviará.')


def execute_sources(prepared,result,config,*,quota=None,operation_id=None):
    from sqlalchemy.exc import SQLAlchemyError
    from utils.db import db
    outcomes={}
    if result['needs_clarification']:
        return {source:{'status':'clarification_required'} for source in prepared['sources']}
    retrieval=prepared
    if prepared.get('attachments') and result.get('query',{}).get('normalized_intent'):
        retrieval={**prepared,'user_message':result['query']['normalized_intent']}
    selected=[source for source in prepared['sources'] if source in EXTERNAL]
    if len(selected)>1:raise PreparationError('Elegí un solo marketplace por ejecución.')
    for source in prepared['sources']:
        if source=='historial':
            outcomes[source]={'status':'failed','error':'El historial no tiene almacenamiento configurado.','data':[]}
        elif source not in EXTERNAL:
            try:outcomes[source]={'status':'complete','data':internal_results(source,retrieval)}
            except SQLAlchemyError:
                db.session.rollback();outcomes[source]={'status':'failed','error':'No se pudieron consultar las publicaciones.'}
    for source in selected:
        outcomes[source]=dispatch_external(source,result,config,quota=quota,operation_id=operation_id,**({'base44':True} if source=='amazon' and prepared.get('image_pipeline')=='base44' else {}))
    return outcomes
