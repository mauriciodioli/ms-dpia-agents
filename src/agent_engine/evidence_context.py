"""Loss-aware structural compaction. No semantic summaries or first-N selection."""
import copy
import hashlib
import json
from .errors import EngineError


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def compact(objective, outputs, *, max_bytes=24000):
    original=encoded({'request':objective,'previous_results':outputs})
    value={'request':objective,'previous_results':copy.deepcopy(list(outputs))}
    # Deduplicate exact records only. Conflicting records are deliberately retained.
    duplicates=0
    for output in value['previous_results']:
        for key in ('items','findings','sources','warnings'):
            if not isinstance(output.get(key),list):continue
            seen=set();rows=[]
            for row in output[key]:
                digest=hashlib.sha256(encoded(row)).digest()
                if digest in seen: duplicates+=1
                else: seen.add(digest);rows.append(row)
            output[key]=rows
    omitted=[]
    def shorten(node, limit, path=''):
        if isinstance(node,dict):
            for key,item in node.items():
                location=path+'/'+key
                # Never truncate titles, URLs, identifiers, prices or currency.
                if key in ('summary','description','descripcion','text') and isinstance(item,str) and len(item)>limit:
                    if key=='text':
                        try:
                            record=json.loads(item)
                            if isinstance(record,dict):
                                shorten(record,limit,location);node[key]=encoded(record).decode();continue
                        except (ValueError,TypeError):pass
                        # Unstructured prose may contain critical identifiers or
                        # prices: do not guess which part can safely be dropped.
                        continue
                    if key=='summary' and not node.get('items'):continue
                    omitted.append({'path':location,'original_chars':len(item),'retained_chars':limit})
                    node[key]=item[:limit]
                else: shorten(item,limit,location)
        elif isinstance(node,list):
            for i,item in enumerate(node):shorten(item,limit,path+'/'+str(i))
    for limit in (2000,1000,500,240,120):
        if len(encoded(value))<=max_bytes:break
        shorten(value['previous_results'],limit,'/previous_results')
    result=encoded(value)
    if len(result)>max_bytes:raise EngineError('analysis_input_limit',409)
    return result.decode(),{'original_bytes':len(original),'final_bytes':len(result),
        'duplicates_removed':duplicates,'omitted':omitted,
        'original_sha256':hashlib.sha256(original).hexdigest(),
        'token_count':None,'token_count_method':'not_measured; UTF-8 byte limit enforced'}
