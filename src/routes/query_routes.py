"""Prepare a verified query; generation transport requires an API contract."""
from flask import Blueprint, jsonify, request, session, current_app
from sqlalchemy.exc import SQLAlchemyError
from services.dpia_client import CatalogError
from services.query_preparation import PreparationError, prepare_context, public_summary, build_private_prompt
from utils.db import db
from services.scraping_quota import self_topup_allowed
from services.result_generation import generate, sheet_rows

query_bp = Blueprint('queries', __name__, url_prefix='/api/consultas')


@query_bp.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@query_bp.post('/preparar')
def prepare():
    if type(session.get('user_id')) is not int:
        return jsonify(success=False, error='Iniciá sesión para preparar la consulta.'), 401
    try:
        prepared = prepare_context(request.get_json(silent=True), session['user_id'])
        # Construct only on the server. It is neither returned nor stored in a session cookie.
        build_private_prompt(prepared)
        return jsonify(success=True, summary=public_summary(prepared), context=prepared['context'],
                       generation_available=bool(prepared['mode'] in ('novedades','explorar') and current_app.config.get('OPENAI_API_KEY') and current_app.config.get('LIVE_PROVIDER_CALLS_ENABLED') and (prepared['mode']=='explorar' or current_app.extensions.get('scraping_quota'))),
                       external_execution_available=bool(current_app.config.get('LIVE_PROVIDER_CALLS_ENABLED') and current_app.extensions.get('scraping_quota')),history_available=bool(current_app.extensions.get('scraping_quota')))
    except PreparationError as exc:
        return jsonify(success=False, error=str(exc)), exc.status
    except CatalogError:
        return jsonify(success=False, error='No se pudo verificar el catálogo. Reintentá.'), 502
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False, error='No se pudo verificar el contexto de la consulta.'), 503


def persistence_unavailable():
    return jsonify(success=False,code='persistence_not_configured',payments_enabled=False,
                   error='El almacenamiento del contador y del historial no está configurado.'),503


@query_bp.get('/creditos')
def scraping_credits():
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión para ver tus ejecuciones.'),401
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    try:
        return jsonify(success=True,credits=quota.credits(session['user_id']),
                       test_credits_enabled=test_credits_enabled(),self_topup_enabled=self_topup_allowed(session['user_id']),payments_enabled=False)
    except PreparationError as exc:
        return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:
        return persistence_unavailable()


def test_credits_enabled():
    return bool(current_app.debug and current_app.config.get('ENABLE_TEST_SCRAPING_CREDITS',False))


@query_bp.post('/creditos/prueba')
def grant_test_credits():
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión.'),401
    if not test_credits_enabled():
        return jsonify(success=False,error='Recargas de prueba deshabilitadas.'),403
    # JSON + same-origin fetch header prevents cross-site form submissions.
    if not request.is_json or request.headers.get('X-DPIA-Test-Credits')!='1':
        return jsonify(success=False,error='Solicitud inválida.'),400
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    try:
        quota.grant_test(session['user_id'])
        return jsonify(success=True,credits=quota.credits(session['user_id']))
    except PreparationError as exc:
        return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:
        return persistence_unavailable()


@query_bp.post('/creditos/recargar')
def self_credit_points():
    from uuid import UUID
    from urllib.parse import urlsplit
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión.'),401
    try:
        origin=request.headers.get('Origin')
        same_origin=not origin or urlsplit(origin).netloc==request.host
    except ValueError:same_origin=False
    if not same_origin or request.headers.get('Sec-Fetch-Site')=='cross-site' or request.headers.get('X-DPIA-Action')!='self-credit':
        return jsonify(success=False,error='Solicitud inválida.'),403
    if not request.is_json or (request.content_length or 0)>4096:
        return jsonify(success=False,error='Solicitud inválida.'),400
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or set(body)!={'amount','request_id'} or not isinstance(body.get('request_id'),str):
        return jsonify(success=False,error='Solicitud inválida.'),400
    try:
        request_id=str(UUID(body['request_id']))
    except (ValueError,AttributeError):
        return jsonify(success=False,error='Solicitud inválida.'),400
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    try:
        result=quota.grant_points(session['user_id'],body['amount'],request_id)
        return jsonify(success=True,**result,credits=quota.credits(session['user_id']))
    except PreparationError as exc:return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:return persistence_unavailable()


@query_bp.get('/operaciones/<operation_id>')
def query_operation(operation_id):
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión.'),401
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    try:
        operation=quota.operation(operation_id,session['user_id'])
        if not operation:return jsonify(success=False,error='Operación no encontrada.'),404
        import json
        from services.query_preparation import result_template
        outcome=json.loads(operation['outcome']) if operation.get('outcome') else {'status':'pending','products':[]}
        from services.base44_images import public_stage
        if 'image_stages' in outcome:outcome['image_stages']={k:public_stage(v) for k,v in outcome['image_stages'].items()}
        generated=outcome.get('generation_result')
        payload=dict(result=generated or result_template(operation['prepared']),rows=sheet_rows(generated) if generated else [],request_id=operation_id,
                     sources={operation['source']:outcome})
        return jsonify(success=True,state=operation['state'],payload=payload)
    except PreparationError as exc:
        return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:
        return persistence_unavailable()


@query_bp.post('/generar')
def generate_query():
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión para generar la consulta.'),401
    import re
    import uuid
    from services.query_sources import EXTERNAL
    from services.query_execution import execute_sources
    from services.query_preparation import result_template
    try:
        body=request.get_json(silent=True)
        from services.query_sources import require_enabled_marketplaces
        if isinstance(body,dict) and body.get('mode')!='explorar':require_enabled_marketplaces(body.get('sources'))
        prepared=prepare_context(body,session['user_id'])
        if prepared['mode']=='explorar':
            if not current_app.config.get('LIVE_PROVIDER_CALLS_ENABLED'):
                raise PreparationError('Las llamadas reales están deshabilitadas.',503)
            result=generate(prepared,current_app.config)
            return jsonify(success=True,flow='explorar',result=result,rows=sheet_rows(result),sources={},
                           context_ids=prepared['ids'])
        external=[source for source in prepared['sources'] if source in EXTERNAL]
        if len(external)>1:
            raise PreparationError('Elegí un solo marketplace por ejecución.')
        if prepared['mode']=='novedades' and external:
            quota=current_app.extensions.get('scraping_quota')
            if quota is None:return persistence_unavailable()
            from services.novel_query import run_novelties, validate_configuration
            validate_configuration(current_app.config)
            try:operation_id=str(uuid.UUID(body.get('request_id','')))
            except (ValueError,TypeError,AttributeError):raise PreparationError('Identificador de consulta inválido.') from None
            return jsonify(run_novelties(prepared,current_app.config,quota,operation_id,generate))
        # No replacement persistence is installed implicitly. Paid execution stays
        # blocked until its server-side counter and replay protection are configured.
        if external or prepared.get('attachments'):
            return persistence_unavailable()
        request_id=body.get('request_id') or str(uuid.uuid4())
        if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',request_id):
            raise PreparationError('Identificador de consulta inválido.')
        result=result_template(prepared)
        outcomes=execute_sources(prepared,result,current_app.config)
        return jsonify(success=True,result=result,rows=sheet_rows(result),sources=outcomes,
                       request_id=request_id,internal_only=True,context_ids=prepared['ids'])
    except PreparationError as exc:
        if exc.status==402:
            return jsonify(success=False,code='insufficient_credit',error=str(exc),required=1,missing=1,
                credits=current_app.extensions['scraping_quota'].credits(session['user_id'])),402
        return jsonify(success=False,error=str(exc),not_started=getattr(exc,'not_started',False)),exc.status
    except CatalogError:
        return jsonify(success=False,error='No se pudo verificar el catálogo.'),502
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False,error='No se pudo verificar la consulta.'),503


@query_bp.post('/scraping-directo')
def direct_scraping():
    """Text-only scraping. Never invoke OpenAI or bypass durable reservations."""
    import uuid
    from services.query_sources import EXTERNAL
    from services.query_preparation import result_template
    from services.query_execution import execute_sources
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión para buscar.'),401
    try:
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or not isinstance(body.get('sources'),list):
            raise PreparationError('Elegí expresamente un marketplace para iniciar scraping.')
        if len(body['sources'])!=1 or body['sources'][0] not in EXTERNAL:
            raise PreparationError('Elegí un solo marketplace para scraping directo.')
        from services.query_sources import require_enabled_marketplaces
        require_enabled_marketplaces(body['sources'])
        if body.get('attachments') or body.get('mode')!='buscar':
            raise PreparationError('El scraping directo admite únicamente texto de búsqueda.')
        try:
            operation_id=str(uuid.UUID(body.get('request_id','')))
        except (ValueError,TypeError,AttributeError):
            raise PreparationError('Identificador de consulta inválido.') from None
        pipeline=body.get('image_pipeline')
        if pipeline is not None and (pipeline!='base44' or body['sources']!=['amazon']):
            raise PreparationError('Esta preparación de imágenes solo admite Amazon.')
        prepared=prepare_context({k:v for k,v in body.items() if k!='image_pipeline'},session['user_id'])
        if pipeline:prepared['image_pipeline']=pipeline
        if len(prepared['user_message'])>500:
            raise PreparationError('La búsqueda directa admite hasta 500 caracteres.')
        # The durable repository must reserve atomically and enforce per-user
        # idempotency, payload identity and the six-execution limit. No memory store.
        quota=current_app.extensions.get('scraping_quota')
        if quota is None:
            return persistence_unavailable()
        quota.reserve_direct(operation_id,session['user_id'],prepared)
        result=result_template(prepared)
        for plan in result['scrape_plan']:
            plan['search_query']=prepared['user_message']
        outcomes=execute_sources(prepared,result,current_app.config,quota=quota,operation_id=operation_id)
        return jsonify(success=True,result=result,rows=[],sources=outcomes,
                       request_id=operation_id,flow='direct_scraping')
    except PreparationError as exc:
        if exc.status==402:
            return jsonify(success=False,code='insufficient_credit',error=str(exc),required=1,missing=1,
                           credits=current_app.extensions['scraping_quota'].credits(session['user_id'])),402
        return jsonify(success=False,error=str(exc)),exc.status
    except CatalogError:
        return jsonify(success=False,error='No se pudo verificar el catálogo.'),502
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False,error='No se pudo verificar la consulta.'),503


@query_bp.get('/historial')
def query_history():
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión para ver tu historial.'),401
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    offset=request.args.get('offset','0')
    if not offset.isdecimal() or len(offset)>6:
        return jsonify(success=False,error='Página inválida.'),400
    try:
        from model.usuario import Usuario
        user=db.session.get(Usuario,session['user_id'])
        if not user or not user.activo:return jsonify(success=False,error='Iniciá sesión.'),401
        return jsonify(success=True,**quota.history(session['user_id'],int(offset)))
    except PreparationError as exc:
        return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:
        return persistence_unavailable()


@query_bp.route('/operaciones/<operation_id>/imagenes',methods=['GET','POST'])
def query_product_images(operation_id):
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión para preparar imágenes.'),401
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    try:
        if request.method=='GET':
            from model.usuario import Usuario
            from services.base44_images import public_stage
            user=db.session.get(Usuario,session['user_id'])
            if not user or not user.activo:raise PreparationError('Iniciá sesión.',401)
            value=request.args.get('product_index','')
            if set(request.args)!={'product_index'} or not value.isdigit() or len(value)>8:
                raise PreparationError('Seleccioná un producto válido.')
            index=int(value);operation=quota.operation(operation_id,session['user_id'])
            if not operation:raise PreparationError('Operación no encontrada.',404)
            import json
            outcome=json.loads(operation['outcome']) if operation.get('outcome') else {}
            if not 0<=index<len(outcome.get('products') or []):raise PreparationError('Producto no encontrado.',404)
            stage=outcome.get('image_stages',{}).get(str(index))
            public=public_stage(stage or {'status':'not_started','images':[]})
            if stage and stage.get('status') in ('pending','loading','running') and stage.get('queue_kind')!='base44_images':
                public.update(tracking_supported=False,error='El intento anterior no tiene un resultado confirmado. Pulsá Preparar imágenes para autorizar otro envío; puede consumir puntos.')
            from services.base44_images import valid_uuid
            if public.get('status')!='complete' and not valid_uuid((outcome.get('base44') or {}).get('trabajo_id')):
                from services.query_images import image_search_body
                public.update(search_required=True,search_body=image_search_body(operation))
            return jsonify(success=True,**public)
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)-{'product_index','filters','confirmed'} or type(body.get('product_index')) is not int:
            raise PreparationError('Seleccioná un producto del resultado guardado.')
        if 'confirmed' in body and type(body['confirmed']) is not bool:
            raise PreparationError('Confirmación inválida.')
        from services.query_images import prepare_images
        return jsonify(prepare_images(quota,operation_id,session['user_id'],body['product_index'],
                                      body.get('filters',{}),current_app.config,confirmed=body.get('confirmed',False)))
    except PreparationError as exc:
        return jsonify(success=False,error=str(exc),**({'code':'image_search_required','search_body':exc.search_body} if hasattr(exc,'search_body') else {})),exc.status
    except SQLAlchemyError:
        return persistence_unavailable()


@query_bp.get('/imagenes/seguimiento')
def image_tracking():
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión.'),401
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    try:
        import time
        from model.usuario import Usuario
        from services.base44_images import public_stage
        user=db.session.get(Usuario,session['user_id'])
        if not user or not user.activo:raise PreparationError('Iniciá sesión.',401)
        tasks=quota.image_tasks(session['user_id'])
        tasks=[dict(operation_id=t['operation_id'],product_index=t['product_index'],product=t['product'],
                    stage=public_stage(t['stage'])) for t in tasks
               if t['stage'].get('status') in ('pending','running') or t['stage'].get('updated_at',0)>time.time()-86400]
        return jsonify(success=True,preparations=tasks)
    except PreparationError as exc:return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:return persistence_unavailable()


@query_bp.post('/operaciones/<operation_id>/publicar')
def publish_query_product(operation_id):
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión para publicar.'),401
    quota=current_app.extensions.get('scraping_quota')
    if quota is None:return persistence_unavailable()
    try:
        from services.query_publication import publish_product
        return jsonify(publish_product(quota,operation_id,session['user_id'],request.get_json(silent=True)))
    except PreparationError as exc:
        return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:
        return jsonify(success=False,error='No se confirmó el guardado. Consultá tus publicaciones antes de reintentar.'),503


@query_bp.route('/historial/scrapeador',methods=['GET','POST'])
def shared_scraper_history():
    if type(session.get('user_id')) is not int:
        return jsonify(success=False,error='Iniciá sesión para consultar el historial.'),401
    try:
        from services.scraper_history import ScraperHistory
        from services.query_execution import normalize_products
        client=ScraperHistory(session['user_id'],current_app.config)
        if request.method=='GET':
            country=request.args.get('pais','');filename=request.args.get('archivo')
            if filename is None:return jsonify(success=True,trabajos=client.listing(country))
            groups=client.load(country,filename)
            products=normalize_products(groups,'amazon')
            errors=any(bool(group.get('error')) for group in groups)
            status=('partial' if products else 'failed') if errors else ('complete' if products else 'empty')
            return jsonify(success=True,payload={'rows':[],'result':{'needs_clarification':False},
                'origin':'scraper_api','remote_job':{'pais':country,'archivo':filename},
                'sources':{'amazon':{'status':status,'products':products}}})
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)-{'pais','archivo','filters'} or not isinstance(body.get('archivo'),str):
            raise PreparationError('Seleccioná un trabajo válido del historial.')
        return jsonify(client.images(body.get('pais'),body['archivo'],body.get('filters',{})))
    except PreparationError as exc:
        return jsonify(success=False,error=str(exc)),exc.status
    except SQLAlchemyError:
        return jsonify(success=False,error='No se pudo verificar el acceso al historial.'),503
