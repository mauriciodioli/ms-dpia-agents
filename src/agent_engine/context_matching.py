"""Deterministic context isolation. No provider calls or changes to authorization."""
import json
import unicodedata

FIELDS = ('objective', 'country', 'city', 'scope_id', 'category_id', 'language')

def normalized(value):
    if isinstance(value, str):
        return unicodedata.normalize('NFKC', value).strip().casefold()
    return value

def initial_context(agent):
    try:
        value = json.loads(agent.get('instructions', ''))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}

def match_context(initial, requested):
    matches = {key: key in initial and key in requested and
               normalized(initial[key]) == normalized(requested[key]) for key in FIELDS}
    complete = all(matches.values())
    # Missing fields are intentionally not filled from the initial agent.
    return dict(status='complete' if complete else 'partial' if any(matches.values()) else 'independent',
                matched=[key for key in FIELDS if matches[key]],
                inherited=[], discarded=[key for key in FIELDS if key in initial and not matches[key]],
                effective=dict(requested))

def resolve(agent, body):
    initial = agent.get('_initial_context', initial_context(agent))
    task = agent.get('_task_context')
    requested = dict(task or {})
    for step in body.get('pipeline', []):
        for key in FIELDS:
            value = step.get('parameters', {}).get(key)
            if value is not None and key not in requested: requested[key] = value
    instructions = body.get('instructions') or body.get('objective')
    if instructions and not task: requested['prompt'] = instructions
    report = match_context(initial, requested)
    initial_tools = set(agent.get('search_parameters', {}))
    requested_tools = {step['tool'] for step in body.get('pipeline', [])}
    report['tools'] = {'shared':sorted(initial_tools & requested_tools),
                       'discarded':sorted(initial_tools - requested_tools),
                       'requested':sorted(requested_tools)}
    effective = dict(agent)
    if requested:
        # Reuse only structured provider defaults with explicit compatible anchors.
        safe = {}
        for tool, params in agent.get('search_parameters', {}).items():
            values = {}
            for key, value in params.items():
                if key not in FIELDS or key not in report['matched']: continue
                if key == 'city' and 'country' not in report['matched']: continue
                if key in ('scope_id', 'category_id') and 'objective' not in report['matched']: continue
                if normalized(value) == normalized(requested[key]):
                    values[key] = value
                    report['inherited'].append(tool + ':' + key)
            if values: safe[tool] = values
        effective['search_parameters'] = safe
        effective['instructions'] = requested.get('prompt') or instructions or agent['instructions']
        location = ', '.join(str(requested[key]) for key in ('city', 'country') if requested.get(key))
        if location: effective['instructions'] += '\nUbicación de esta tarea: ' + location + '.'
    else:
        # An explicit plan without context must not receive unrelated defaults.
        effective['search_parameters'] = {}
        effective['instructions'] = instructions or 'Ejecutar únicamente el plan solicitado.'
    report['discarded_tool_parameters'] = {
        tool: [key for key in params if key not in effective['search_parameters'].get(tool, {})]
        for tool, params in agent.get('search_parameters', {}).items()}
    report['effective_instructions'] = effective['instructions']
    return effective, report
