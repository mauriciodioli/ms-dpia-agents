"""Deterministic result cards from provider records; never infer missing facts."""
import json
import re
from urllib.parse import urlsplit


def web_url(value):
    if not isinstance(value,str):return ''
    try:
        parsed=urlsplit(value.strip())
        return value.strip() if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password and len(value)<=2000 else ''
    except ValueError:return ''


def excerpt(value, maximum=8000):
    text=' '.join(value.split()) if isinstance(value,str) else ''
    if len(text)<=maximum:return text
    return text[:maximum-1].rsplit(' ',1)[0]+'…'


def records(value):
    if isinstance(value,list):return [row for row in value if isinstance(row,dict)]
    if not isinstance(value,dict):return []
    for key in ('results','items'):
        if isinstance(value.get(key),list):return records(value[key])
    for key in ('data','result'):
        found=records(value.get(key))
        if found:return found
    return []


def text_records(text):
    try:
        found=records(json.loads(text))
        if found:return found
    except (ValueError,TypeError):pass
    # Exa's text transport uses explicit record labels, including in older saved results.
    pattern=r'\bTitle:\s*(.*?)\s+URL:\s*(https?://\S+)(.*?)(?=\bTitle:\s*.*?\s+URL:\s*https?://|\Z)'
    output=[]
    for match in re.finditer(pattern,text,re.S):
        title,url,body=match.groups()
        published=re.search(r'\bPublished:\s*(.*?)(?=\s+Author:|\s+Highlights:|\Z)',body,re.S)
        description=re.split(r'\b(?:Highlights|Text|Content):\s*',body,maxsplit=1)
        row={'title':title,'url':url.rstrip('.,'),'description':description[-1] if len(description)>1 else ''}
        if published:row['published_at']=published.group(1).strip()
        output.append(row)
    return output


def card(row):
    title=row.get('title') or row.get('titulo')
    url=web_url(row.get('url') or row.get('link'))
    if not isinstance(title,str) or not title.strip() or not url:return None
    description=row.get('description') or row.get('descripcion') or row.get('text') or row.get('highlights') or ''
    if isinstance(description,list):description=' '.join(part for part in description if isinstance(part,str))
    item={'title':excerpt(title,1000),'url':url,'description':excerpt(description)}
    for key,aliases in {'published_at':('published_at','publishedDate'), 'company':('company',), 'location':('location',), 'image':('image','image_url')}.items():
        value=next((row.get(alias) for alias in aliases if isinstance(row.get(alias),str) and row.get(alias).strip()),None)
        if value and value.strip().upper() not in ('N/A','N/D','UNKNOWN','NULL'):
            if key=='image':value=web_url(value)
            if value:item[key]=excerpt(value,2000 if key=='image' else 120)
    return item


def present_result(payload, structured=None, retrieved_at=None):
    """Return a compatible view; never mutate the stored payload or its evidence status."""
    if payload.get('items'):return payload
    rows=records(structured) if structured is not None else []
    if not rows:rows=text_records(payload.get('summary',''))
    items=[];seen=set()
    for row in rows:
        item=card(row)
        if item and item['url'] not in seen:
            items.append(item);seen.add(item['url'])
        if len(items)==100:break
    if not items:return payload
    sources=list(payload.get('sources',[]))
    if retrieved_at and not sources:
        sources=[{'id':'source-'+str(i+1),'url':item['url'],'title':item['title'],'retrieved_at':retrieved_at} for i,item in enumerate(items)]
    output={**payload,'summary':f'Se encontraron {len(items)} resultados. Consultá los detalles y enlaces de cada tarjeta.', 'items':items,'sources':sources}
    while len(json.dumps(output,ensure_ascii=False).encode('utf-8'))>240000 and len(items)>1:
        items.pop()
        if retrieved_at and not payload.get('sources'):sources.pop()
        output['summary']=f'Se encontraron {len(items)} resultados. Consultá los detalles y enlaces de cada tarjeta.'
    return output
