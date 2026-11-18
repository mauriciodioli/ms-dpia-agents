"""Extract commercial records without inventing prices, currencies or identities."""
import json,re
from urllib.parse import urlsplit
from decimal import Decimal,InvalidOperation
from .identity import canonical_url,offer_key
from ..result_presentation import records

def commercial_rows(payload,depth=0):
    if depth>8:return []
    found=[]
    for row in records(payload):
        if any(k in row for k in ('title','titulo')):found.append(row)
        else:found.extend(commercial_rows(row,depth+1))
    if isinstance(payload,dict) and isinstance(payload.get('sources'),dict):
        for value in payload['sources'].values():found.extend(commercial_rows(value,depth+1))
    return found


def normalize(payload,*,job_id,observed_at,source):
    errors=[];products=[]
    if not isinstance(payload,dict):return [],['invalid_product_payload']
    rows=commercial_rows(payload)
    for finding in payload.get('findings',[]):
        text=finding.get('text') if isinstance(finding,dict) else None
        if not isinstance(text,str) or not text.lstrip().startswith(('{','[')):continue
        try:value=json.loads(text,parse_float=Decimal)
        except (ValueError,TypeError):errors.append('malformed_commercial_json');continue
        if isinstance(value,dict):rows.append(value)
        elif isinstance(value,list):rows.extend(row for row in value if isinstance(row,dict))
    for row in rows:
        if not isinstance(row,dict):errors.append('invalid_product_record');continue
        def get(*keys):return next((row[k] for k in keys if row.get(k) is not None and row[k]!=''),None)
        # Generic informational cards (e.g. job listings) are not products.
        if not any(k in row for k in ('marketplace','asin','sku','product_id','precio','price','moneda','currency')):continue
        title=get('title','titulo');url=canonical_url(get('url','product_url'))
        if not isinstance(title,str) or not title.strip():errors.append('product_title_missing');continue
        price=get('precio','price');currency=get('moneda','currency')
        if price is not None:
            try:
                if isinstance(price,bool):raise ValueError()
                price=Decimal(str(price))
                if not price.is_finite() or price<0 or price>=Decimal('1000000000000') or price!=price.quantize(Decimal('0.0001')):raise ValueError()
            except (ValueError,InvalidOperation):errors.append('invalid_product_price');continue
        if currency is not None and (not isinstance(currency,str) or not re.fullmatch('[A-Za-z]{3}',currency)):
            errors.append('invalid_product_currency');continue
        seller=get('seller_id','vendedor_id','seller','vendedor')
        if isinstance(seller,dict):seller=seller.get('id') or seller.get('name')
        product=dict(marketplace=get('marketplace','source'),external_id=get('asin','product_id','sku'),url=url,
                     title=title.strip(),price=price,currency=currency.upper() if currency else None,
                     seller=str(seller) if seller is not None else None,location=get('location','ubicacion'),
                     country=get('country','pais'),observed_at=observed_at,job_id=job_id,source=source)
        if url:product['provider_marketplace']=product['marketplace'];product['marketplace']=(urlsplit(url).hostname or '').removeprefix('www.')
        for key in ('marketplace','external_id','country','location'):
            if product[key] is not None and not isinstance(product[key],str):product[key]=str(product[key])
        try:product['offer_key']=offer_key(product)
        except ValueError as e:errors.append(str(e));continue
        limits={'title':500,'marketplace':80,'external_id':255,'seller':255,'location':255}
        if any(isinstance(product[k],str) and len(product[k])>limit for k,limit in limits.items()):errors.append('product_field_too_long');continue
        products.append(product)
    return products,errors
