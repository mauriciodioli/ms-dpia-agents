"""Image preparation from owned persisted products, using DPIA's persisted Base44 pipeline.

Filter semantics match filtro_publicacion.validar_filtros_scraper and diagnostics
in dpia-popup-service. No generated prices, margins or media URLs.
"""
import json
import math
import re
from urllib.parse import urlsplit
import requests
from services.dpia_client import DPIAClient
from model.usuario import Usuario
from utils.db import db
from services.query_execution import normalize_products, safe_product_url
from services.query_preparation import PreparationError

DEFAULTS = dict(precio_minimo=0, precio_maximo=None, rating_minimo=4.4, resenas_minimas=50)


def validate_filters(value, *, optional=False):
    if not isinstance(value, dict) or set(value)-set(DEFAULTS):
        raise PreparationError('Filtros no reconocidos.')
    defaults={**DEFAULTS,'rating_minimo':None,'resenas_minimas':None} if optional else DEFAULTS
    result = {**defaults, **value}
    for key, number in result.items():
        if number is None and (key=='precio_maximo' or optional and key in ('rating_minimo','resenas_minimas')):continue
        if type(number) not in (int,float) or not math.isfinite(number) or number<0:
            raise PreparationError('Los filtros deben ser números finitos no negativos.')
    rating,reviews=result['rating_minimo'],result['resenas_minimas']
    if ((rating is not None and (rating<0 or rating>5 or not optional and rating==0)) or
            (reviews is not None and (type(reviews) is not int or reviews<(0 if optional else 1)))):
        raise PreparationError('Revisá el rating mínimo y la cantidad de reseñas.')
    if result['precio_maximo'] is not None and result['precio_maximo']<result['precio_minimo']:
        raise PreparationError('El precio máximo no puede ser menor al mínimo.')
    return result


def number(value):
    if value is None or value=='':return None
    if type(value) in (int,float):return float(value) if math.isfinite(value) else None
    match=re.search(r'(\d+[.,]?\d*)',str(value))
    parsed=float(match[1].replace(',','.')) if match else None
    return parsed if parsed is not None and math.isfinite(parsed) else None


def diagnostics(item, filters):
    price,rating=number(item.get('precio')),number(item.get('rating'))
    match=re.search(r'(\d[\d.,]*)',str(item.get('reviews') or ''))
    reviews=int(match[1].replace('.','').replace(',','')) if match else 0
    checks={'precio':bool(price and price>0 and price>=filters['precio_minimo'] and
              (filters['precio_maximo'] is None or price<=filters['precio_maximo'])),
            'rating':filters['rating_minimo'] is None or rating is None or rating>=filters['rating_minimo'],
            'resenas':filters['resenas_minimas'] is None or rating is None or reviews>=filters['resenas_minimas']}
    return {'eligible':all(checks.values()),'checks':checks,'price':price,'rating':rating,
            'reviews':reviews,'rating_missing':rating is None}


def raw_product(operation, index):
    outcome=json.loads(operation['outcome']) if operation.get('outcome') else {}
    products=outcome.get('products') or []
    if type(index) is not int or not 0<=index<len(products):
        raise PreparationError('Producto no encontrado.',404)
    selected=products[index]
    for group in outcome.get('data') or []:
        if not isinstance(group,dict):continue
        for item in group.get('items') or []:
            normalized=normalize_products([{'items':[item]}],operation['source'])
            if normalized and normalized[0]==selected:
                return item
    raise PreparationError('No se pudo verificar el producto original.',409)


def image_search_body(operation):
    prepared=operation['prepared'];context=prepared['context']
    return {**{k:context[k] for k in ('pais','ciudad','idioma')},**prepared['ids'],
        'mode':'buscar','sources':['amazon'],'attachments':[],'image_pipeline':'base44',
        'user_message':prepared['user_message']}


def prepare_images(quota, operation_id, user_id, index, filters, config, *, confirmed=False):
    user=db.session.get(Usuario,user_id)
    if not user or not user.activo:raise PreparationError('Iniciá sesión con un usuario activo.',401)
    operation=quota.operation(operation_id,user_id)
    if not operation:raise PreparationError('Operación no encontrada.',404)
    if operation['source']!='amazon':raise PreparationError('La galería por ASIN está disponible para Amazon.')
    item=raw_product(operation,index)
    filters=validate_filters(filters,optional=True);diagnosis=diagnostics(item,filters)
    if not diagnosis['eligible']:
        return {'success':True,'status':'filtered','images':[],'diagnostics':diagnosis,'filters':filters}
    from services.base44_images import Base44Images, valid_uuid, product_reference, public_stage
    outcome=json.loads(operation['outcome'])
    old=outcome.get('image_stages',{}).get(str(index),{})
    if old and old.get('status')!='complete' and not confirmed:
        raise PreparationError('Confirmá la preparación de imágenes: puede consumir puntos.',409)
    if old.get('queue_kind')=='base44_images' and old.get('status')!='complete':
        old=quota.image_task(operation_id,user_id,index,retry=True)
    if old.get('status')=='complete' or old.get('queue_kind')=='base44_images':
        return {'success':True,**public_stage(old),'diagnostics':diagnosis}
    reference=outcome.get('base44') or {}
    job_id=reference.get('trabajo_id')
    if not valid_uuid(job_id):
        error=PreparationError('Esta búsqueda anterior no creó un trabajo compatible con imágenes. Podés autorizar una nueva búsqueda Amazon.',409)
        error.search_body=image_search_body(operation)
        raise error
    if not config.get('LIVE_PROVIDER_CALLS_ENABLED',False):
        raise PreparationError('Las llamadas reales están deshabilitadas.',503)
    client=Base44Images(config);client.authorize()
    job=client.job(job_id);product_id=product_reference(job,item)
    stage=quota.image_task(operation_id,user_id,index,initial={
        'trabajo_id':job_id,'producto_id':product_id,'filters':filters,'diagnostics':diagnosis,'images':[]},replace_legacy=old if old else None)
    return {'success':True,**public_stage(stage)}
