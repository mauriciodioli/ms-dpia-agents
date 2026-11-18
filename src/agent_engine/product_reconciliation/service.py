"""Reconcile definitive accepted product results, inside the caller's transaction."""
import logging
from sqlalchemy import MetaData,Table,select,inspect
from .. import models as m
from ..errors import EngineError
from .normalizer import normalize
from .comparator import compare
from .repository import Repository,json_safe
from .identity import canonical_url

COUNTS={'NUEVO':'nuevos','PRECIO_BAJO':'precio_bajo','PRECIO_SUBIO':'precio_subio','DATOS_CAMBIARON':'datos_cambiaron','SIN_CAMBIOS':'sin_cambios'}

def reconcile_job(conn,owner_id,agent_id,job_id,dry_run=True):
    summary=dict(productos_validos=0,nuevos=0,precio_bajo=0,precio_subio=0,datos_cambiaron=0,sin_cambios=0,rechazados=0,errores=[],productos=[],duplicados=0,dry_run=dry_run)
    if type(dry_run) is not bool:raise EngineError('invalid_contract')
    agent=conn.execute(select(m.agents).where(m.agents.c.id==agent_id,m.agents.c.owner_id==owner_id).with_for_update() if not dry_run else select(m.agents).where(m.agents.c.id==agent_id,m.agents.c.owner_id==owner_id)).mappings().first()
    job=conn.execute(select(m.jobs).where(m.jobs.c.id==job_id,m.jobs.c.owner_id==owner_id,m.jobs.c.agent_id==agent_id)).mappings().first()
    if not agent or not job:raise EngineError('reconciliation_not_found',404)
    legacy_id=agent['legacy_agent_id']
    if legacy_id is None:summary['bloqueo']='reconciliation_legacy_agent_required';return summary
    if not inspect(conn).has_table('agentes'):summary['bloqueo']='reconciliation_legacy_storage_required';return summary
    legacy=Table('agentes',MetaData(),autoload_with=conn,resolve_fks=False)
    query=select(legacy).where(legacy.c.id==legacy_id,legacy.c.usuario_id==owner_id)
    if not dry_run:query=query.with_for_update()
    if conn.execute(query).first() is None:raise EngineError('reconciliation_owner_mismatch',403)
    assessment=job['configuration_snapshot'].get('result_assessment',{})
    if job['state']!='DELIVERED' or assessment.get('result_classification')!='SATISFIED':
        summary['bloqueo']='reconciliation_result_not_definitive';return summary
    result=conn.execute(select(m.results).where(m.results.c.owner_id==owner_id,m.results.c.job_id==job_id).order_by(m.results.c.version.desc()).limit(1)).mappings().first()
    if not result or assessment.get('result_id')!=result['id']:
        summary['bloqueo']='reconciliation_result_not_definitive';return summary
    if any(str(w).startswith('PARTIAL_RESULTS') for w in result['payload'].get('warnings',[])):
        summary['bloqueo']='reconciliation_result_not_definitive';return summary
    observed=result['created_at'];payload=result['payload']
    products,errors=normalize(payload,job_id=job_id,observed_at=observed,source='ae_results:'+result['id'])
    # Original provider fields enrich only offers accepted in the final result.
    accepted={canonical_url(r.get('url')) for r in payload.get('items',[]) if isinstance(r,dict)}|{p['url'] for p in products}
    outputs=conn.execute(select(m.tasks.c.id,m.tasks.c.output).where(m.tasks.c.owner_id==owner_id,m.tasks.c.job_id==job_id,m.tasks.c.state=='COMPLETED')).mappings()
    raw_products=[]
    for output in outputs:
        raw,raw_errors=normalize(output['output'],job_id=job_id,observed_at=observed,source='ae_tasks:'+output['id'])
        raw_products.extend(p for p in raw if p['url'] and p['url'] in accepted)
        errors.extend(raw_errors)
    # Consolidated cards/findings can omit an ID or seller retained in raw output.
    # Enrich identity before deduplication instead of creating a second URL-only offer.
    from .identity import offer_key
    merged=[]
    for product in products:
        matches=[p for p in raw_products if p['url']==product['url'] and product['url']
                 and (not product['seller'] or p['seller']==product['seller'])
                 and (not product['external_id'] or p['external_id']==product['external_id'])]
        if not matches:merged.append(product);continue
        for raw in matches:
            enriched={k:raw.get(k) if raw.get(k) is not None else v for k,v in product.items()}
            enriched['offer_key']=offer_key(enriched)
            # Preserve canonical facts so a conflicting raw price is rejected below.
            accepted_version={**enriched,**{k:product[k] for k in ('price','currency') if product[k] is not None}}
            merged.extend([enriched,accepted_version])
    products=merged+raw_products
    unique={}
    for p in products:
        key=p['offer_key']
        if key in unique:
            old=unique[key]
            if old is None:continue
            # Conflicting commercial observations in a single job are not guessed.
            if any(old[k] is not None and p[k] is not None and old[k]!=p[k] for k in ('price','currency')):
                unique[key]=None;errors.append('conflicting_product_observations');continue
            unique[key]={k:old.get(k) if old.get(k) is not None else v for k,v in p.items()}
        else:unique[key]=p
    products=[p for p in unique.values() if p is not None]
    summary['productos_validos']=len(products);summary['rechazados']=len(errors);summary['errores']=errors
    try:repo=Repository(conn,dry_run=dry_run)
    except EngineError as e:summary['bloqueo']=e.code;return summary
    execution_id=repo.legacy_execution(legacy_id,job_id)
    # A savepoint makes direct invocation atomic even if caller catches an error.
    with conn.begin_nested():
        for product in products:
            existing=repo.existing(legacy_id,job_id,product['offer_key'])
            if existing:
                value=existing['datos']['reconciliation'];kind=value['kind'];details=value['details'];summary['duplicados']+=1
            else:
                previous,old=repo.latest(legacy_id,product['offer_key'],observed)
                if old is None:old=repo.historical(owner_id,agent_id,legacy_id,product['offer_key'],observed)
                kind,details=compare(old,product)
                if not dry_run:repo.store(legacy_id,job_id,product,kind,details,previous['id'] if previous else None,execution_id)
            summary[COUNTS[kind]]+=1
            summary['productos'].append(json_safe({'clave':product['offer_key'],'clasificacion':kind,'detalle':details}))
    return summary


def reconcile_delivered(conn,owner_id,agent_id,job_id):
    """Best effort savepoint: commercial history never prevents delivery."""
    try:
        with conn.begin_nested():
            value=reconcile_job(conn,owner_id,agent_id,job_id,dry_run=False)
        if value.get('bloqueo'):logging.getLogger(__name__).warning('Product reconciliation blocked code=%s',value['bloqueo'])
        return value
    except Exception:
        # No payload, identifiers, credentials or exception message in logs.
        logging.getLogger(__name__).warning('Product reconciliation failed code=reconciliation_storage_failed')
        return {'bloqueo':'reconciliation_storage_failed'}
