"""Read cities and postal IDs from the existing codigo_postal table."""
from sqlalchemy import func
import unicodedata
from model.codigoPostal import CodigoPostal


def city_key(value):
    """Match saved UI names such as Poznań against legacy 'poznan' rows."""
    decomposed = unicodedata.normalize('NFKD', value)
    return ' '.join(''.join(c for c in decomposed if not unicodedata.combining(c)).casefold().split())


def cities_for_country(country):
    rows = CodigoPostal.query.filter(
        func.lower(func.trim(CodigoPostal.pais)) == country.strip().lower(),
        CodigoPostal.ciudad.isnot(None),
    ).order_by(CodigoPostal.ciudad, CodigoPostal.id).all()
    cities = {}
    for row in rows:
        name = row.ciudad.strip()
        if not name:
            continue
        item = cities.setdefault(city_key(name), {'nombre': name, 'codigo_postal_ids': []})
        item['codigo_postal_ids'].append(row.id)
    for item in cities.values():
        item['codigo_postal_ids'].sort()
    return sorted(cities.values(), key=lambda item: item['nombre'].casefold())


def postal_ids_for_city(country, city):
    return next((item['codigo_postal_ids'] for item in cities_for_country(country)
                 if city_key(item['nombre']) == city_key(city)), [])
