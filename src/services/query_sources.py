"""Source preferences are data; only external marketplaces can dispatch scraping."""
import re
from services.query_preparation import PreparationError

EXTERNAL=('amazon','ebay','aliexpress','mercadolibre')
# Enable another marketplace only after its API and DB storage are ready.
ENABLED_EXTERNAL=('amazon','mercadolibre')
INTERNAL=('local','dpia','historial')
ALL=EXTERNAL+INTERNAL


def normalize_sources(value):
    if value is None:return ['amazon']
    if not isinstance(value,list) or not value or len(value)>7 or any(not isinstance(s,str) for s in value):
        raise PreparationError('Seleccioná al menos un origen de búsqueda.')
    if any(s not in (*ALL,'todos') for s in value):raise PreparationError('Origen de búsqueda inválido.')
    return list(ALL) if 'todos' in value else [s for s in ALL if s in value]


def require_enabled_marketplaces(value):
    sources=normalize_sources(value)
    if any(source in EXTERNAL and source not in ENABLED_EXTERNAL for source in sources):
        raise PreparationError('El marketplace seleccionado todavía no está habilitado para scraping.',400)


def search_terms(message):
    ignored={'busco','buscar','quiero','necesito','encontrar','productos','producto','de','en','para','con','y','o','la','las','el','los','un','una','me','por','favor','find','search','for','the','and','cerca','locales','publicaciones'}
    return [term for term in re.findall(r'\w+',message.lower()) if len(term)>2 and term not in ignored][:8]
