"""Manager-owned canonical JSON; raw provider outputs remain in ae_tasks.output."""
from .contracts import RESULT, validate
from .result_presentation import records, text_records, card


def normalize(output):
    rows = records(output)
    if not rows: rows = text_records(output.get('summary', ''))
    if not rows and output.get('schema_version') != 'agents.result.v1': return None
    payload = {key:output.get(key, default) for key,default in
               (('summary',''),('findings',[]),('sources',[]),('warnings',[]))}
    payload['schema_version'] = 'agents.result.v1'
    items = []; seen = set()
    for row in rows:
        item = card(row)
        if item and item['url'] not in seen:
            items.append(item); seen.add(item['url'])
    if items: payload['items'] = items[:100]
    validate(RESULT, payload)
    return payload


def consolidate(outputs):
    values = [value for value in (normalize(output) for output in outputs) if value is not None]
    if not values:return None
    # Source identifiers are local to each Worker output; preserve references
    # when two providers use the same identifier for different URLs.
    used = {}
    for index,value in enumerate(values):
        mapping={}; sources=[]
        for source in value['sources']:
            identifier=source['id']
            if identifier in used and used[identifier] != source['url']:
                identifier=f'step-{index+1}-'+identifier[:90]
                while identifier in used and used[identifier]!=source['url']: identifier='x-'+identifier[:117]
            used[identifier]=source['url'];mapping[source['id']]=identifier
            sources.append({**source,'id':identifier})
        value['sources']=sources
        value['findings']=[{**finding,'source_ids':[mapping[key] for key in finding['source_ids']]} for finding in value['findings']]
    result = dict(values[-1])
    for key in ('items','findings','sources','warnings'):
        merged=[]
        for value in values:
            for entry in value.get(key,[]):
                if key == 'items': duplicate = any(old['url']==entry['url'] for old in merged)
                elif key == 'sources': duplicate = any(old['id']==entry['id'] for old in merged)
                else: duplicate = entry in merged
                if not duplicate:merged.append(entry)
        if merged or key != 'items':result[key]=merged
    validate(RESULT,result)
    return result


def persisted_matches(job, tasks, payload):
    if job['configuration_snapshot'].get('canonical_result_version') == 1:
        return consolidate([task['output'] for task in tasks if task['state']=='COMPLETED']) == payload
    return bool(tasks) and tasks[-1]['output'] == payload
