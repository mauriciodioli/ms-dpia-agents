"""Offline cover selection. Only SELECT statements; no work runs on import."""
from collections import defaultdict
from urllib.parse import urlsplit, unquote
import unicodedata
from sqlalchemy import text

LANGUAGES = {'es':'es', 'in':'en', 'en':'en', 'pl':'pl', 'it':'it'}
BUCKET_PREFIX = '/bucket_202404/'


def language_code(value):
    return LANGUAGES.get(str(value or '').strip().lower())


def location_key(country, city):
    def key(value):
        return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', value)
                               if not unicodedata.combining(c)).casefold().split())
    return key(country) + '|' + key(city)


def bucket_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (parsed.scheme != 'https' or parsed.netloc != 'storage.googleapis.com'
            or not parsed.path.startswith(BUCKET_PREFIX) or parsed.query or parsed.fragment
            or '..' in unquote(parsed.path).split('/')):
        return None
    return value


def read_snapshot(connection):
    """Caller owns the read-only transaction. No user details are selected."""
    queries = {
        'publications': 'SELECT id, categoria_id, imagen, estado, codigo_postal_id, codigoPostal FROM publicacion',
        'categories': 'SELECT id, nombre, idioma FROM ambitoCategoria',
        'scopes': 'SELECT id, nombre, idioma FROM ambitos',
        'category_links': 'SELECT publicacion_id, categoria_id, estado FROM categoriaPublicacion',
        'scope_links': 'SELECT ambito_id, ambitoCategoria_id, estado FROM ambitoCategoriaRelation',
        'media': "SELECT piv.id, piv.publicacion_id, i.filepath FROM publicacion_imagen_video piv JOIN image i ON i.id=piv.imagen_id WHERE piv.media_type='imagen' ORDER BY piv.id",
        'postals': 'SELECT id, codigoPostal, pais, ciudad FROM codigo_postal',
        'postal_links': 'SELECT publicacion_id, codigoPostal_id FROM publicacionCodigoPostal',
    }
    return {name: [dict(row) for row in connection.execute(text(sql)).mappings()]
            for name, sql in queries.items()}


def resolve_snapshot(snapshot):
    categories = {r['id']:r for r in snapshot['categories'] if language_code(r['idioma'])}
    scopes = {r['id']:r for r in snapshot['scopes'] if language_code(r['idioma'])}
    active = lambda row: str(row.get('estado', '')).strip().lower() == 'activo'
    category_links, media, postal_links = defaultdict(set), defaultdict(list), defaultdict(set)
    for row in snapshot['category_links']:
        if active(row): category_links[row['publicacion_id']].add(row['categoria_id'])
    for row in snapshot['media']:
        media[row['publicacion_id']].append(row)
    for row in snapshot['postal_links']:
        postal_links[row['publicacion_id']].add(row['codigoPostal_id'])
    parents = defaultdict(set)
    for row in snapshot['scope_links']:
        cat, scope = row['ambitoCategoria_id'], row['ambito_id']
        if active(row) and cat in categories and scope in scopes:
            # Never infer cross-language equivalence from names.
            if language_code(categories[cat]['idioma']) == language_code(scopes[scope]['idioma']):
                parents[cat].add(scope)
    postal_locations, text_postals = {}, defaultdict(set)
    locations = {}
    for row in snapshot['postals']:
        if row['pais'] and row['ciudad']:
            key = location_key(row['pais'],row['ciudad'])
            postal_locations[row['id']] = key
            text_postals[str(row['codigoPostal']).strip()].add(row['id'])
            locations[key] = {'country':row['pais'], 'city':row['ciudad']}
    candidates, excluded = defaultdict(list), []
    for row in sorted(snapshot['publications'], key=lambda r:r['id'], reverse=True):
        if not active(row): continue
        direct, linked = row['categoria_id'], category_links[row['id']]
        if direct is not None and any(cat != direct for cat in linked):
            excluded.append({'publication_id':row['id'], 'reason':'inconsistent_category'}); continue
        ids = {direct} if direct is not None else linked
        if not ids or any(cat not in categories for cat in ids):
            excluded.append({'publication_id':row['id'], 'reason':'unknown_category'}); continue
        postal_ids = set(postal_links[row['id']])
        if row.get('codigo_postal_id') is not None: postal_ids.add(row['codigo_postal_id'])
        if not postal_ids: postal_ids = text_postals[str(row.get('codigoPostal') or '').strip()]
        places = sorted({postal_locations[id] for id in postal_ids if id in postal_locations})
        sources = [('main', row.get('imagen'), None)]
        sources += [('additional', item['filepath'], item['id']) for item in media[row['id']]]
        for kind, url, media_id in sources:
            url = bucket_url(url)
            if not url: continue
            for cat in ids:
                candidates[cat].append({'publication_id':row['id'], 'category_id':cat,
                    'source_url':url, 'source_kind':kind, 'media_id':media_id, 'locations':places})
    for items in candidates.values():
        items.sort(key=lambda r:(r['source_kind'] != 'main', -r['publication_id'], r['media_id'] or 0))
    return {'categories':categories, 'scopes':scopes, 'parents':parents,
            'candidates':candidates, 'locations':locations, 'excluded':excluded}


def select_cover(candidates, previous, load_image):
    """Keep a valid previous source even if newer publications have appeared."""
    ordered = list(candidates)
    if previous:
        identity = lambda row:(row['publication_id'],row['source_url'],row['source_kind'])
        ordered.sort(key=lambda row:identity(row) != identity(previous))
    for candidate in ordered:
        image = load_image(candidate['source_url'])
        if image:
            return {**{k:v for k,v in candidate.items() if k != 'locations'}, **image}
    return None


def build_manifest(resolved, previous, load_image, generated_at):
    manifest = {'version':1, 'generated_at':generated_at, 'languages':{}, 'locations':{}}
    def build_context(place, previous_groups):
        groups = {}
        for language in ('es','en','pl','it'):
            cats, scopes = {}, {}
            prior = previous_groups.get(language,{})
            for id, row in resolved['categories'].items():
                if language_code(row['idioma']) != language: continue
                candidates = [r for r in resolved['candidates'].get(id,[]) if place is None or place in r['locations']]
                image = select_cover(candidates, prior.get('categorias',{}).get(str(id),{}).get('cover'), load_image)
                cats[str(id)] = {'nombre':row['nombre'], 'ambito_ids':sorted(resolved['parents'][id]), 'cover':image}
            for id, row in resolved['scopes'].items():
                if language_code(row['idioma']) != language: continue
                related = [entry['cover'] for entry in cats.values() if id in entry['ambito_ids'] and entry['cover']]
                image = select_cover(related, prior.get('ambitos',{}).get(str(id),{}).get('cover'), load_image)
                scopes[str(id)] = {'nombre':row['nombre'], 'cover':image}
            groups[language] = {'categorias':cats,'ambitos':scopes}
        return groups
    manifest['languages'] = build_context(None, previous.get('languages',{}))
    for key, place in resolved['locations'].items():
        manifest['locations'][key] = {**place, 'languages':build_context(key,previous.get('locations',{}).get(key,{}).get('languages',{}))}
    return manifest


def coverage_report(manifest, resolved, failures):
    def report(groups):
        languages = {}
        for lang, kinds in groups.items():
            scopes, cats = kinds['ambitos'], kinds['categorias']
            unresolved_scopes = [{'id':id,'nombre':r['nombre']} for id,r in scopes.items() if not r['cover']]
            unresolved_cats, fallback = [], []
            for id,row in cats.items():
                if row['cover']: continue
                parents = [parent for parent in row['ambito_ids'] if scopes.get(str(parent),{}).get('cover')]
                entry = {'id':id,'nombre':row['nombre'],'ambito_ids':row['ambito_ids']}
                (fallback if parents else unresolved_cats).append(entry)
            languages[lang] = {'scopes_total':len(scopes),'scopes_photo':len(scopes)-len(unresolved_scopes),
                'categories_total':len(cats),'categories_photo':sum(bool(r['cover']) for r in cats.values()),
                'categories_scope_fallback':len(fallback), 'categories_gradient':len(unresolved_cats),
                'unresolved_scopes':unresolved_scopes,'unresolved_categories':unresolved_cats,'scope_fallback_categories':fallback}
        return languages
    return {'generated_at':manifest['generated_at'],'global':report(manifest['languages']),
            'locations':{key:report(value['languages']) for key,value in manifest['locations'].items()},
            'excluded_publications':resolved['excluded'],'image_failures':failures,
            'note':'Scope fallback requires opening a related scope with a valid cover; otherwise gradient.'}


def coverage_markdown(report):
    lines=['# Cobertura de portadas reales', '', 'Generado: '+report['generated_at'], '',
           'Inventario global. La PWA utiliza la variante de la ciudad seleccionada.', '',
           '| Idioma | Ámbitos con foto / total | Categorías con foto / total | Respaldo de ámbito | Categorías con degradado |',
           '| --- | --- | --- | --- | --- |']
    for lang,row in report['global'].items():
        lines.append(f"| {lang} | {row['scopes_photo']} / {row['scopes_total']} | {row['categories_photo']} / {row['categories_total']} | {row['categories_scope_fallback']} | {row['categories_gradient']} |")
    for lang,row in report['global'].items():
        lines += ['', '## '+lang, '']
        for field,title in [('unresolved_scopes','Ámbitos sin fotografía'),
                            ('unresolved_categories','Categorías sin fotografía propia ni de ámbito'),
                            ('scope_fallback_categories','Categorías con respaldo de ámbito')]:
            lines += ['### '+title, '']
            lines += [f"- `{entry['id']}`: {entry['nombre']}" for entry in row[field]] or ['Ninguno.']
            lines += ['']
    lines += ['## Fuentes no válidas', '']
    lines += [f"- {entry['reason']}: {entry['source_url']}" for entry in report['image_failures']]
    lines += ['', 'El detalle por ciudad, las publicaciones excluidas y los registros con idioma no reconocido están en `coverage.json`.', '']
    return '\n'.join(lines)
