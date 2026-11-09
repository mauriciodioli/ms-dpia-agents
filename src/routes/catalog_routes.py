"""Same-origin catalog endpoints; credentials remain on the server."""
from flask import Blueprint, current_app, jsonify, request
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.exc import SQLAlchemyError
from services.locations import cities_for_country, postal_ids_for_city
from utils.db import db
from model.codigoPostal import CodigoPostal

from services.dpia_client import CatalogError, CatalogFiltersError, DPIAClient, catalog_filters

catalog_bp = Blueprint("catalog", __name__, url_prefix="/api/catalogos")


@catalog_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def load_catalog(name):
    try:
        params = catalog_filters(request.args, name)
        client = DPIAClient(
            current_app.config.get("SCRAPEADOR_SERVICE_KEY", ""),
            timeout=(current_app.config.get("DPIA_CONNECT_TIMEOUT", 3.05),
                     current_app.config.get("DPIA_READ_TIMEOUT", 10)),
        )
        return jsonify(client.catalog(name, params))
    except CatalogFiltersError:
        return jsonify(success=False, error="Filtros de catálogo inválidos."), 400
    except CatalogError as exc:
        return jsonify(success=False, error="No se pudo cargar el catálogo DPIA."), exc.status


@catalog_bp.get("/ambitos")
def ambitos():
    return load_catalog("ambitos")


@catalog_bp.get("/categorias")
def categorias():
    return load_catalog("categorias")


def location_args(with_city=False):
    required = {'pais', 'ciudad', 'idioma'} if with_city else {'pais'}
    if set(request.args) != required:
        raise CatalogFiltersError()
    values = {}
    for key in required:
        if len(request.args.getlist(key)) != 1:
            raise CatalogFiltersError()
        value = request.args[key].strip()
        if not value or len(value) > 100:
            raise CatalogFiltersError()
        values[key] = value
    return values


@catalog_bp.get('/ciudades')
def ciudades():
    try:
        args = location_args()
        return jsonify(success=True, ciudades=cities_for_country(args['pais']))
    except CatalogFiltersError:
        return jsonify(success=False, error='País inválido.'), 400
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False, error='No se pudieron cargar las ciudades.'), 503


@catalog_bp.get('/ubicacion')
def ubicacion():
    try:
        args = location_args(with_city=True)
        # Reuse verified language validation and 'en' -> 'in' mapping.
        from werkzeug.datastructures import MultiDict
        params = catalog_filters(MultiDict({'idioma': args['idioma']}), 'ambitos')
        postal_ids = postal_ids_for_city(args['pais'], args['ciudad'])
        client = DPIAClient(current_app.config.get('SCRAPEADOR_SERVICE_KEY', ''), timeout=(
            current_app.config.get('DPIA_CONNECT_TIMEOUT', 3.05),
            current_app.config.get('DPIA_READ_TIMEOUT', 10)))
        tasks = [(name, postal_id) for name in ('ambitos', 'categorias') for postal_id in postal_ids]
        def fetch(task):
            name, postal_id = task
            return name, client.catalog(name, {**params, 'codigo_postal_id': postal_id})[name]
        combined = {'ambitos': {}, 'categorias': {}}
        # Workers only perform HTTP calls, never share a SQLAlchemy session.
        with ThreadPoolExecutor(max_workers=4) as executor:
            for name, records in executor.map(fetch, tasks):
                for record in records:
                    key = 'ambito_id' if name == 'ambitos' else 'categoria_id'
                    existing = combined[name].get(record[key])
                    if existing and name == 'categorias':
                        existing['ambito_ids'] = sorted(set(existing['ambito_ids'] + record['ambito_ids']))
                    else:
                        combined[name][record[key]] = record
        postal_records=[{'id': row.id, 'codigoPostal':row.codigoPostal} for row in
                        CodigoPostal.query.filter(CodigoPostal.id.in_(postal_ids)).order_by(CodigoPostal.id).all()]
        return jsonify(success=True, codigo_postal_ids=postal_ids, codigos_postales=postal_records, **{
            name: sorted(records.values(), key=lambda item: (item['nombre'].casefold(), item[
                'ambito_id' if name == 'ambitos' else 'categoria_id'])) for name, records in combined.items()})
    except CatalogFiltersError:
        return jsonify(success=False, error='Ubicación o idioma inválidos.'), 400
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False, error='No se pudo cargar la ubicación.'), 503
    except CatalogError as exc:
        return jsonify(success=False, error='No se pudo cargar el catálogo de esta ciudad.'), exc.status
