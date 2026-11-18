"""Manager-owned canonical JSON; raw provider outputs remain in ae_tasks.output."""
import json
from .contracts import RESULT, validate
from .result_presentation import records, text_records, card


def normalize(output):
    rows = records(output)
    if not rows: rows = text_records(output.get('summary', ''))
    if not rows and output.get('schema_version') != 'agents.result.v1': return None
    payload = {key:output.get(key, default) for key,default in
               (('summary',''),('findings',[]),('sources',[]),('warnings',[]))}
    payload['schema_version'] = 'agents.result.v1'
    if output.get('video'):payload['video']=output['video']
    if output.get('video_script'):payload['video_script']=output['video_script']
    items = []; seen = set()
    for row in rows:
        item = card(row)
        if item and item['url'] not in seen:
            items.append(item); seen.add(item['url'])
    if items: payload['items'] = items[:100]
    from .adaptive_steps import product_records
    payload['findings']=list(payload['findings'])
    for record in product_records([{'items':rows}]):
        # The established findings JSON carries commercial fields that are not
        # public card properties. Do not extend agents.result.v1 or invent prices.
        selected={key:value for key,value in record.items() if key in
                  ('title','titulo','url','precio','price','moneda','currency','marketplace','image_url','imagen','image','description','descripcion','asin')}
        encoded=json.dumps(selected,ensure_ascii=False,allow_nan=False)
        if not any(finding['text']==encoded for finding in payload['findings']):
            refs=[source['id'] for source in payload['sources'] if source['url']==record['url']]
            payload['findings'].append({'text':encoded,'source_ids':refs})

    validate(RESULT, payload)
    return payload


def consolidate(outputs, *, partial=False):
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
    if partial and 'PARTIAL_RESULTS: No se completaron todos los requisitos solicitados.' not in result['warnings']:
        result['warnings'].append('PARTIAL_RESULTS: No se completaron todos los requisitos solicitados.')
    validate(RESULT,result)
    return result


def persisted_matches(job, tasks, payload):
    if job['configuration_snapshot'].get('canonical_result_version') == 1:
        partial=any(value.get('reason')=='PARTIAL_JOB_RESULTS' for value in job['configuration_snapshot'].get('manager_decisions',{}).values())
        value=consolidate([task['output'] for task in tasks if task['state']=='COMPLETED'],partial=partial)
        if job['configuration_snapshot'].get('accepted_evidence_urls'):
            value=select_evidence(value,job['configuration_snapshot']['accepted_evidence_urls'])
        return value == payload
    return bool(tasks) and tasks[-1]['output'] == payload


def select_evidence(payload, urls):
    """One business mapping shared by finalization and persisted validation."""
    from .errors import EngineError
    accepted=set(urls)
    result=dict(payload)
    result['items']=[row for row in payload.get('items',[]) if row['url'] in accepted]
    result['sources']=[row for row in payload.get('sources',[]) if row['url'] in accepted]
    source_ids={row['id'] for row in result['sources']}
    result['findings']=[]
    for finding in payload.get('findings',[]):
        try: row=json.loads(finding['text'])
        except (ValueError,TypeError):row={}
        if isinstance(row,dict) and row.get('url') in accepted or (finding['source_ids'] and set(finding['source_ids']).issubset(source_ids)):
            result['findings'].append(finding)
    if not result['items'] and not result['findings']:
        raise EngineError('RESULT_EVIDENCE_SELECTION_EMPTY',409)
    result['summary']='Resultados aceptados por el Manager.'
    validate(RESULT,result)
    return result
