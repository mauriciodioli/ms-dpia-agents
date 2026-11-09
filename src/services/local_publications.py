"""Read active publications for all postal records of a selected city."""
import random
import time

from sqlalchemy import and_, func, or_
from model.codigoPostal import CodigoPostal
from model.publicaciones.publicaciones import Publicacion
from model.publicaciones.publicacionCodigoPostal import PublicacionCodigoPostal
from services.locations import postal_ids_for_city
from utils.db import db


def publications_for_city(country, city, offset=0, category_id=None, terms=None, category_ids=None, rotate=False, promoted_only=False, viewer_id=None, scope='local'):
    normalized_country = func.lower(func.trim(CodigoPostal.pais))
    domestic = db.session.query(CodigoPostal.id).filter(normalized_country == country.strip().lower())
    if scope == 'local':
        ids = postal_ids_for_city(country, city)
    else:
        locations = CodigoPostal.query.filter(CodigoPostal.pais.isnot(None), func.trim(CodigoPostal.pais) != '')
        locations = locations.filter(normalized_country == country.strip().lower() if scope == 'pais' else normalized_country != country.strip().lower())
        ids = [row.id for row in locations.all()]
    if not ids:
        return [], False
    codes = db.session.query(CodigoPostal.codigoPostal).filter(CodigoPostal.id.in_(ids))
    local_relation = db.session.query(PublicacionCodigoPostal.id).filter(
        PublicacionCodigoPostal.publicacion_id == Publicacion.id,
        PublicacionCodigoPostal.codigoPostal_id.in_(ids),
    ).exists()
    any_relation = db.session.query(PublicacionCodigoPostal.id).filter(
        PublicacionCodigoPostal.publicacion_id == Publicacion.id,
    ).exists()
    # Legacy text is used only when there is no explicit postal association.
    local = or_(Publicacion.codigo_postal_id.in_(ids), local_relation, and_(
        Publicacion.codigo_postal_id.is_(None), ~any_relation,
        func.trim(Publicacion.codigoPostal).in_(codes),
    ))
    if scope == 'exterior':
        # A shared domestic association must never leak into foreign results.
        domestic_relation = db.session.query(PublicacionCodigoPostal.id).filter(
            PublicacionCodigoPostal.publicacion_id == Publicacion.id,
            PublicacionCodigoPostal.codigoPostal_id.in_(domestic)).exists()
        domestic_codes = db.session.query(CodigoPostal.codigoPostal).filter(CodigoPostal.id.in_(domestic))
        local = and_(local, or_(Publicacion.codigo_postal_id.is_(None), ~Publicacion.codigo_postal_id.in_(domestic)),
                     ~domestic_relation,
                     ~and_(Publicacion.codigo_postal_id.is_(None), ~any_relation, func.coalesce(Publicacion.codigoPostal, '').in_(domestic_codes)))
    query = Publicacion.query.filter(
        func.lower(func.trim(Publicacion.estado)) == 'activo', local,
    )
    if promoted_only:
        from services.publication_promotions import active_publication_ids
        query = query.filter(Publicacion.id.in_(active_publication_ids(viewer_id)))
        if viewer_id is not None:
            query = query.filter(Publicacion.user_id != viewer_id)
    if category_id is not None:
        query = query.filter(Publicacion.categoria_id == category_id)
    if category_ids is not None:
        query = query.filter(Publicacion.categoria_id.in_(category_ids))
    if terms:
        query = query.filter(or_(*(or_(Publicacion.titulo.ilike('%'+term+'%'), Publicacion.texto.ilike('%'+term+'%'), Publicacion.descripcion.ilike('%'+term+'%')) for term in terms)))
    ordered = query.order_by(Publicacion.fecha_creacion.desc(), Publicacion.id.desc())
    if rotate:
        # Rotate over the entire matching catalogue, not only the newest page.
        bucket = int(time.time()) // (48 * 60 * 60)
        total = query.count()
        start = bucket % total if total else 0
        rows = ordered.offset(start).limit(min(total, 24)).all()
        if len(rows) < min(total, 24):
            rows += ordered.limit(min(total, 24) - len(rows)).all()
        random.Random(bucket).shuffle(rows)
    else:
        rows = ordered.offset(offset).limit(25).all()
    return [dict(id=row.id, titulo=row.titulo, descripcion=row.descripcion,
                 imagen=row.imagen, precio=row.precio, moneda=row.moneda,
                 ciudad=city) for row in rows[:24]], (total > 24 if rotate else len(rows) > 24)
