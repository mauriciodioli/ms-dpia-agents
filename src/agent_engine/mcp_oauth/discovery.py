"""MCP protected-resource / RFC8414 / OpenID metadata discovery."""
import re
from urllib.parse import urlsplit,parse_qsl
from .http import secure_url
from ..errors import EngineError

def origin(url):
    p=urlsplit(url);return p.scheme+'://'+p.netloc

def discover(http,resource,configured):
    secure_url(resource)
    candidates=[]
    if configured.get('resource_metadata_url'):candidates.append(secure_url(configured['resource_metadata_url']))
    else:
        status,_,headers=http.get(resource)
        challenge=headers.get('www-authenticate','')
        match=re.search(r'\bresource_metadata="([^"\r\n]+)"',challenge)
        if match:candidates.append(secure_url(match.group(1)))
        path=urlsplit(resource).path.rstrip('/')
        candidates.extend([origin(resource)+'/.well-known/oauth-protected-resource'+path,origin(resource)+'/.well-known/oauth-protected-resource'])
    prm=None
    for url in dict.fromkeys(candidates):
        status,value,_=http.get(url)
        if status==200:prm=value;break
    if not prm or not isinstance(prm.get('resource'),str) or prm['resource'].rstrip('/')!=resource.rstrip('/'):
        raise EngineError('mcp_oauth_resource_metadata_invalid',502)
    issuers=prm.get('authorization_servers')
    if not isinstance(issuers,list) or not issuers or any(not isinstance(x,str) for x in issuers):raise EngineError('mcp_oauth_issuer_missing',502)
    issuer=configured.get('issuer')
    if issuer is None:
        if len(issuers)!=1:raise EngineError('mcp_oauth_issuer_selection_required',422)
        issuer=issuers[0]
    if issuer not in issuers:raise EngineError('mcp_oauth_issuer_mismatch',502)
    secure_url(issuer);p=urlsplit(issuer);path=p.path.rstrip('/')
    urls=[origin(issuer)+'/.well-known/oauth-authorization-server'+path,
          origin(issuer)+'/.well-known/openid-configuration'+path,
          issuer.rstrip('/')+'/.well-known/openid-configuration']
    metadata=None
    for url in dict.fromkeys(urls):
        status,value,_=http.get(url)
        if status==200:metadata=value;break
    if not metadata or metadata.get('issuer')!=issuer:raise EngineError('mcp_oauth_issuer_mismatch',502)
    for key in ('authorization_endpoint','token_endpoint','registration_endpoint','revocation_endpoint'):
        if key not in metadata:
            if key in ('authorization_endpoint','token_endpoint'):raise EngineError('mcp_oauth_invalid_metadata',502)
            continue
        secure_url(metadata[key],query=key=='authorization_endpoint')
        # Deliberately fail closed for cross-origin token/client-secret endpoints.
        if origin(metadata[key])!=origin(issuer):raise EngineError('mcp_oauth_endpoint_origin_mismatch',422)
    if 'S256' not in metadata.get('code_challenge_methods_supported',[]):raise EngineError('mcp_oauth_pkce_required',422)
    if 'code' not in metadata.get('response_types_supported',['code']):raise EngineError('mcp_oauth_invalid_metadata',502)
    if set(dict(parse_qsl(urlsplit(metadata['authorization_endpoint']).query)))&{'state','redirect_uri','client_id','response_type','code_challenge','code_challenge_method','resource','scope'}:raise EngineError('mcp_oauth_invalid_metadata',502)
    scopes=configured.get('scope')
    if scopes is None:
        advertised=prm.get('scopes_supported',[])
        if not isinstance(advertised,list) or any(not isinstance(s,str) for s in advertised):raise EngineError('mcp_oauth_invalid_scope',502)
        scopes=' '.join(advertised)
    if not isinstance(scopes,str) or len(scopes)>2000 or any(ord(c)<32 for c in scopes):raise EngineError('mcp_oauth_invalid_scope',422)
    return {'resource':resource,'issuer':issuer,'authorization':metadata,'scope':scopes}
