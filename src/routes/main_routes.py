"""Rutas de las páginas principales de la aplicación."""
from flask import Blueprint, render_template, make_response

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
@main_bp.get("/agents")
@main_bp.get("/agents/new")
@main_bp.get("/agents/<agent_id>/edit")
@main_bp.get("/schedules")
@main_bp.get("/executions")
@main_bp.get("/integrations")
@main_bp.get("/administration")
def index(agent_id=None):
    response = make_response(render_template("agents_workspace.html"))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


@main_bp.get('/api/publicaciones/locales')
def local_publications():
    from flask import jsonify, request, current_app, session
    from sqlalchemy.exc import SQLAlchemyError
    from services.local_publications import publications_for_city
    from utils.db import db
    country = request.args.get('pais', '').strip()
    city = request.args.get('ciudad', '').strip()
    scope = request.args.get('alcance', 'local')
    if scope not in ('local','pais','exterior'):
        return jsonify(success=False, error='Alcance inválido.'), 400
    offset = request.args.get('offset', '0')
    if (not country or not city or len(country) > 100 or len(city) > 100
            or not offset.isdecimal() or len(offset) > 6):
        return jsonify(success=False, error='Elegí un país y una ciudad válidos.'), 400
    search = request.args.get('q', '').strip()
    if len(search) > 500:
        return jsonify(success=False, error='La búsqueda local admite hasta 500 caracteres.'), 400
    category = request.args.get('categoria_id')
    if category is not None and (not category.isdecimal() or len(category) > 10
                                 or not 1 <= int(category) <= 2147483647):
        return jsonify(success=False, error='Categoría inválida.'), 400
    include_promotions=request.args.get('promociones','0')
    if include_promotions not in ('0','1','solo'):
        return jsonify(success=False,error='Promociones inválidas.'),400
    rotation = request.args.get('rotar', '0')
    if rotation not in ('0','1'):
        return jsonify(success=False, error='Rotación inválida.'), 400
    category_ids = request.args.get('categoria_ids')
    if category_ids is not None:
        values = category_ids.split(',')
        if len(values)>500 or any(not value.isdecimal() or len(value)>10 or not 1<=int(value)<=2147483647 for value in values):
            return jsonify(success=False, error='Categorías inválidas.'), 400
        category_ids = list({int(value) for value in values})
    try:
        from services.query_sources import search_terms
        if include_promotions=='solo':
            items,more=[],False
        else:
            items, more = publications_for_city(country, city, int(offset),
                                            int(category) if category is not None else None, terms=search_terms(search), category_ids=category_ids, rotate=rotation=='1', **({'scope':scope} if scope!='local' else {}))
        if include_promotions in ('1','solo') and scope == 'local':
            viewer_id=session.get('user_id') if type(session.get('user_id')) is int else None
            featured, featured_more=publications_for_city(country, city, rotate=True, promoted_only=True, viewer_id=viewer_id)
            for item in featured:item['destacado']=True
            featured_ids={item['id'] for item in featured}
            combined=featured+[item for item in items if item['id'] not in featured_ids]
            more=more or featured_more or len(combined)>24
            items=combined[:24]
        response = jsonify(success=True, publicaciones=items, has_more=more)
        response.headers['Cache-Control'] = 'no-store'
        return response
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.warning('Local publications query failed')
        return jsonify(success=False, error='No se pudieron cargar las publicaciones locales.'), 503


@main_bp.get('/api/conexion')
def api_connection():
    """Sanitized same-origin API check, independent of scraping and user points."""
    from flask import current_app, jsonify
    from services.dpia_client import DPIAClient, ConnectionCheckError
    try:
        result = DPIAClient(current_app.config.get('SCRAPEADOR_SERVICE_KEY', ''), timeout=(2, 5)).check_connection()
        response = jsonify(result)
    except ConnectionCheckError as exc:
        response = jsonify(success=False, code=exc.code)
        response.status_code = exc.status
    response.headers['Cache-Control'] = 'no-store'
    return response
