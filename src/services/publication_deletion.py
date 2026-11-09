"""Delete one owned publication atomically; never touch buckets or scraper jobs."""
from sqlalchemy import MetaData, Table, delete, inspect, select, text
from werkzeug.exceptions import Conflict, NotFound
from utils.db import db

# Only publication-owned junction rows may be removed. Every other reference
# (orders, popups, chats, scraper jobs, etc.) blocks deletion conservatively.
ASSOCIATIONS = {
    'categoriaPublicacion': 'publicacion_id',
    'publicacionCodigoPostal': 'publicacion_id',
    'ambito_usuario': 'publicacion_id',
    'estado_publi_usu': 'publicacion_id',
    'usuarioPublicacionUbicacion': 'id_publicacion',
    'publicacion_imagen_video': 'publicacion_id',
}
REFERENCE_NAMES = ('publicacion_id', 'id_publicacion', 'publication_id')


def reference_columns(conn):
    if conn.dialect.name == 'mysql':
        # One metadata read also finds references not represented by local models.
        rows = conn.execute(text('''
            SELECT DISTINCT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND COLUMN_NAME IN ('publicacion_id', 'id_publicacion', 'publication_id')
            UNION
            SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME = 'publicacion'
              AND REFERENCED_COLUMN_NAME = 'id'
        '''))
        return sorted(set(rows))
    inspector = inspect(conn)
    refs = set()
    for name in inspector.get_table_names():
        refs.update((name, col['name']) for col in inspector.get_columns(name)
                    if col['name'] in REFERENCE_NAMES)
        for fk in inspector.get_foreign_keys(name):
            if fk.get('referred_table') == 'publicacion':
                refs.update((name, col) for col in fk['constrained_columns'])
    return sorted(refs)


def delete_owned_publication(publication_id, user_id):
    with db.engine.begin() as conn:
        metadata = MetaData()
        publication = Table('publicacion', metadata, autoload_with=conn, resolve_fks=False)
        owner = conn.execute(select(publication.c.id).where(
            publication.c.id == publication_id, publication.c.user_id == user_id
        ).with_for_update()).first()
        if owner is None:
            raise NotFound('Publicación no encontrada.')
        junctions = []
        for name, column in reference_columns(conn):
            table = Table(name, metadata, autoload_with=conn, resolve_fks=False)
            condition = table.c[column] == publication_id
            if ASSOCIATIONS.get(name) == column:
                junctions.append((table, condition))
            elif conn.execute(select(table.c[column]).where(condition).limit(1).with_for_update()).first():
                raise Conflict('La publicación está vinculada a pedidos, trabajos u otros registros. No se eliminó.')
        for table, condition in junctions:
            conn.execute(delete(table).where(condition))
        conn.execute(delete(publication).where(publication.c.id == publication_id,
                                               publication.c.user_id == user_id))
    # Image/video records and external URLs are retained, including shared media.
    return {'success': True, 'eliminado': True, 'publicacion_id': publication_id}
