"""Category-independent task titles. Never mutate the original request or configuration."""
import re
import unicodedata

MAX_TASK_NAME = 120
TARGET_TASK_NAME = 80


def validate_task_name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_TASK_NAME
            or any(unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError('El nombre de la tarea debe tener entre 1 y 120 caracteres válidos.')
    return value


def task_name(request, *, city=''):
    """Extract action/object/location without cutting the first N request characters.

    This path has no AI generation. Scheduling and secondary requirements stay in
    query_context; a word budget applies only to the extracted title concepts.
    Unknown categories use the same rules, with no category dispatch table.
    """
    if not isinstance(request, str) or not request.strip():
        raise ValueError('La tarea necesita un pedido.')
    text = ' '.join(''.join(' ' if unicodedata.category(c).startswith('C') else c
                            for c in request).split())
    text = re.sub(r'^(?:por favor[, ]+)?(?:todos los \w+|cada \w+|semanalmente|diariamente)[, ]+', '', text, flags=re.I)
    actions = {'buscá': 'Buscar', 'busca': 'Buscar', 'buscar': 'Buscar',
               'analizá': 'Analizar', 'analiza': 'Analizar', 'analizar': 'Analizar',
               'monitoreá': 'Monitorear', 'monitorea': 'Monitorear', 'monitorear': 'Monitorear',
               'compará': 'Comparar', 'compara': 'Comparar', 'comparar': 'Comparar',
               'identificá': 'Identificar', 'identifica': 'Identificar', 'identificar': 'Identificar'}
    first, _, rest = text.partition(' ')
    action = actions.get(first.casefold(), 'Buscar')
    if first.casefold() in actions:
        text = rest
    # Secondary instructions are not part of the main object of the request.
    text = re.split(r'[,;.!?]|\b(?:incluyendo|incluí|incluye|con el objetivo|y detect[aá]|y busc[aá])\b', text, maxsplit=1, flags=re.I)[0]
    substitutions = ((r'\bofertas laborales\b', 'empleos'),
                     (r'\binteligencia artificial\b', 'IA'),
                     (r'\bBackend Developer\b', 'Backend'),
                     (r'\b(?:reales|recientes)\b', ''),
                     (r'\by\s+(?=para\b)', ''))
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text, flags=re.I)
    if re.search(r'compar[aá].*precios', request, re.I) and re.search(r'proveedores', request, re.I):
        action = 'Monitorear'
        text = 'precios y proveedores de ' + re.sub(r'\b(?:nuevos|nuevas)\b', '', text, flags=re.I)
    location = ' '.join(city.split()) if isinstance(city, str) else ''
    # Keep location separately so that a long object cannot crowd it out.
    if location:
        text = re.sub(r'\s+en\s+' + re.escape(location) + r'\b', '', text, flags=re.I)
    suffix = ' en ' + location if location and len(location) <= 35 else ''
    words = text.split()
    budget = TARGET_TASK_NAME - len(action) - len(suffix) - 1
    if len(' '.join(words)) > budget:
        words = [w for w in words if w.casefold() not in {'nuevos','nuevas','nuevo','nueva','todos','todas','muy','más'}]
    selected = []
    for word in words:
        if len(' '.join(selected + [word])) <= budget:
            selected.append(word)
    while selected and selected[-1].casefold() in {'de','del','para','en','con','y','el','la','los','las'}:
        selected.pop()
    if not selected:
        selected = ['oportunidades']
    return validate_task_name(action + ' ' + ' '.join(selected) + suffix)


def normalize_task_payload(payload):
    """Copy an outbound create/edit payload, changing only an invalid/long name.

    Valid explicit titles are preserved, including titles between 81 and 120.
    No nested instructions, tool arguments or optimistic revision are rewritten.
    """
    result = dict(payload)
    try:
        validate_task_name(result.get('name'))
    except ValueError:
        result['name'] = task_name(result.get('name') or result.get('instructions', ''))
    validate_task_name(result['name'])
    return result


def legacy_task_name(task, city=''):
    """Use recorded information only; never infer a role, product or location."""
    params = task.get('parametros') or {}
    config = params.get('_agent_configuration') or {}
    if isinstance(config, dict):
        explicit = config.get('name')
        try:
            return validate_task_name(explicit)
        except ValueError:
            pass
        instruction = config.get('instructions')
        if isinstance(instruction, str) and instruction.strip():
            return task_name(instruction, city=city)
    context = params.get('query_context') or {}
    if isinstance(context, dict) and isinstance(context.get('prompt'), str) and context['prompt'].strip():
        return task_name(context['prompt'], city=city)
    kind = task.get('tipo')
    if isinstance(kind, str) and kind.strip():
        return task_name(kind.replace('_', ' ').lower(), city=city)
    return validate_task_name('Tarea ' + str(task['id']))
