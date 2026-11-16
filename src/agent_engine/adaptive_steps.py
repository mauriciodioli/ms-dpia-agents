"""Resolve existing planned dependencies from persisted outputs. No provider calls."""
import json
import re
import math
from urllib.parse import urlsplit
from .result_presentation import web_url, records
from .errors import EngineError


def commercial_objective(text):
    return bool(re.search(r'producto|reventa|revender|comercial|products?|resale',text.casefold()))


def product_records(outputs):
    products=[]
    for output in outputs:
        rows=list(records(output))
        for finding in output.get('findings',[]):
            try:
                value=json.loads(finding['text'])
                if isinstance(value,dict): rows.append(value)
            except (ValueError,TypeError,KeyError):pass
        for row in rows:
            title=row.get('title') or row.get('titulo')
            url=web_url(row.get('url'))
            price=row.get('precio',row.get('price'))
            currency=row.get('moneda') or row.get('currency')
            try: priced=math.isfinite(float(price)) and float(price)>=0 and isinstance(currency,str) and bool(currency.strip())
            except (TypeError,ValueError):priced=False
            if isinstance(title,str) and title.strip() and url and priced:
                products.append(row)
    return products


def references(parameters):
    for key,value in parameters.items():
        if isinstance(value,dict):yield from references(value)
        elif isinstance(value,list):
            for item in value:
                if isinstance(item,dict):yield from references(item)
                elif isinstance(item,str) and (key in ('urls','url','search_url') or item.startswith(('http://','https://'))):yield item
        elif isinstance(value,str) and (key in ('url','search_url') or value.startswith(('http://','https://'))):yield value


def real_reference(value):
    if not web_url(value):return False
    parsed=urlsplit(value);host=(parsed.hostname or '').casefold()
    return not (host in ('example.com','example.org','example.net','example.test') or
        re.search(r'placeholder|B0[XxYy]{4,}|[<{].*[>}]',value))


def resolve_parameters(step, completed, registry):
    """Returns parameters and provenance for a waiting, previously authorized step."""
    original=dict(step['input_snapshot'].get('parameters',{}));params=dict(original)
    spec=registry.tools.get(step['tool_id'])
    if spec is None:raise EngineError('job_tool_unavailable',409)
    properties=spec.input_schema.get('properties',{})
    outputs=[item['output'] for item in completed]
    provenance=[]
    # Semantic bindings are proposed by the Manager's durable reasoner. Never
    # turn article headlines or arbitrary bullets into commercial product terms.
    if 'query' in properties and 'max_products' in properties and completed:
        if not step['input_snapshot'].get('manager_bound'):
            raise EngineError('dependent_search_requires_reasoning',409)
        provenance=[item['id'] for item in completed]
    if 'urls' in properties and completed:
        urls=[]
        for item in completed:
            output=item['output']
            candidates=[row.get('url') for row in product_records([output])]
            if not candidates:candidates=[row.get('url') for row in records(output)]
            for url in candidates:
                if real_reference(url) and url not in urls:urls.append(url);provenance.append(item['id'])
        if not urls:raise EngineError('dependent_urls_missing',409)
        params['urls']=urls[:properties['urls'].get('maxItems',10)]
    if any(not real_reference(url) for url in references(params)):
        raise EngineError('unsafe_planned_reference',409)
    registry.validate_step({'tool':step['tool_id'],'parameters':params},{step['tool_id']})
    return params, {'task_ids':sorted(set(provenance)),'original_parameters':original,'effective_parameters':params}


def relevant_products(job, output, objective):
    """Use resolved search subjects when available, not operational instructions."""
    import unicodedata
    def tokens(text):
        text=''.join(c for c in unicodedata.normalize('NFKD',str(text).casefold()) if not unicodedata.combining(c))
        return set(re.findall(r'\w+',text))
    queries=[binding.get('effective_parameters',{}).get('query','') for binding in
             job['configuration_snapshot'].get('dependency_bindings',{}).values()]
    noise={'or','de','en','y','con','para','productos','producto','products','moda','actuales',
           'encontrar','buscar','precios','precio','potencial','reventa','italia','mercado','comerciales'}
    anchors=tokens(' '.join(queries) or objective)-noise
    anchors={word for word in anchors if len(word)>2}
    return [product for product in product_records([output]) if not anchors or anchors &
            tokens(' '.join(str(product.get(key,'')) for key in ('title','titulo','description','descripcion')))]
