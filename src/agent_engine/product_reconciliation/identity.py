"""Offer identity, independent of price and display title."""
import hashlib,json
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

def canonical_url(value):
    from ..result_presentation import web_url
    if not web_url(value):return None
    p=urlsplit(value)
    if p.username or p.password:return None
    query=sorted((k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in {'ref','tag','fbclid','gclid'})
    return urlunsplit(('https',p.netloc.lower(),p.path.rstrip('/') or '/',urlencode(query),''))

def offer_key(product):
    url=canonical_url(product.get('url'))
    market=product.get('marketplace') or (urlsplit(url).hostname if url else None)
    external=product.get('external_id')
    if not market or not (external or url):raise ValueError('identity_missing')
    # Seller remains part of the offer; unknown seller never matches a named seller.
    identity=[str(market).strip().casefold(),product.get('country') or '',
              str(product.get('seller') or '').strip().casefold(),
              ['id',str(external).strip()] if external else ['url',url]]
    return hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
