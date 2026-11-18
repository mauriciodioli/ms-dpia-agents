"""Owner/resource-bound OAuth. HTTP is outside database transactions."""
import base64,hashlib,json,secrets
from datetime import timedelta
from urllib.parse import urlencode,urlsplit,parse_qsl,urlunsplit
from sqlalchemy import select,insert,update
from cryptography.fernet import InvalidToken
from ..auth import now_utc
from ..errors import EngineError
from ..integrations import IntegrationService
from ..mcp_repository import MCPRepository
from ..mcp_service import access
from .models import connections,flows
from .http import OAuthHTTP,secure_url
from .discovery import discover

CALLBACK='/api/agents/v1/mcp/oauth/callback'

def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')

class OAuthService:
 def __init__(self,engine,config,http=None):
  self.engine,self.config=engine,config;self.http=http or OAuthHTTP();self.secrets=IntegrationService(engine,config)
 def seal(self,value):return self.secrets.cipher().encrypt(json.dumps(value,allow_nan=False).encode()).decode()
 def unseal(self,value):
  try:return json.loads(self.secrets.cipher().decrypt(value.encode()).decode())
  except (InvalidToken,ValueError,AttributeError,UnicodeError):raise EngineError('integration_encryption_unavailable',503) from None
 def callback_url(self):
  value=self.config.get('MCP_OAUTH_CALLBACK_URL','')
  try:secure_url(value)
  except EngineError:raise EngineError('mcp_oauth_callback_not_configured',503) from None
  if urlsplit(value).path!=CALLBACK:raise EngineError('mcp_oauth_callback_not_configured',503)
  return value
 def configured(self,server):
  config=self.config.get('MCP_OAUTH_CLIENTS_JSON','{}')
  try:config=json.loads(config) if isinstance(config,str) else config
  except ValueError:raise EngineError('mcp_oauth_configuration_invalid',503) from None
  if not isinstance(config,dict) or not isinstance(config.get(server['endpoint_url'],{}),dict):raise EngineError('mcp_oauth_configuration_invalid',503)
  return config.get(server['endpoint_url'],{})
 def row(self,conn,owner,server,lock=False):
  q=select(connections).where(connections.c.owner_id==owner,connections.c.server_id==server)
  return conn.execute(q.with_for_update() if lock else q).mappings().first()
 def server(self,conn,principal,identifier,scope='mcp:write'):
  access(conn,principal,scope);row=dict(MCPRepository(conn).server(identifier,principal))
  if row['auth_type']!='oauth':raise EngineError('mcp_oauth_not_configured',409)
  return row
 def state(self,principal,identifier):
  with self.engine.connect() as c:
   server=self.server(c,principal,identifier,'mcp:read');row=self.row(c,principal.owner_id,identifier)
   status=row['status'] if row and row['resource_url']==server['endpoint_url'] else 'DISCONNECTED'
   if status=='CONNECTING':
    flow=c.execute(select(flows.c.expires_at).where(flows.c.state_hash==row['active_flow'])).scalar_one_or_none()
    if flow is None or flow<=now_utc():return {'status':'ERROR','connected':False,'error_code':'mcp_oauth_authorization_expired'}
   if status=='CONNECTED' and row['expires_at'] and row['expires_at']<=now_utc() and not self.unseal(row['tokens_ciphertext']).get('refresh_token'):status='ERROR'
   return {'status':status,'connected':status=='CONNECTED','error_code':row['error_code'] if row else None}
 def client(self,metadata,configured,redirect,existing=None):
  if configured.get('client_id'):
   if configured.get('client_secret') and not configured.get('issuer'):raise EngineError('mcp_oauth_client_configuration_required',422)
   client={k:configured[k] for k in ('client_id','client_secret','token_endpoint_auth_method') if k in configured}
  elif existing:client=self.unseal(existing)
  else:
   endpoint=metadata['authorization'].get('registration_endpoint')
   if not endpoint:raise EngineError('mcp_oauth_client_configuration_required',422)
   status,client,_=self.http.register(endpoint,{'client_name':'DPIA Agents','redirect_uris':[redirect],
       'grant_types':['authorization_code','refresh_token'],'response_types':['code'],'token_endpoint_auth_method':'none'})
   if status not in (200,201):raise EngineError('mcp_oauth_registration_failed',502)
   if client.get('redirect_uris')!=[redirect]:raise EngineError('mcp_oauth_registration_failed',502)
  if not isinstance(client.get('client_id'),str) or not 1<=len(client['client_id'])<=2048:raise EngineError('mcp_oauth_registration_failed',502)
  method=client.get('token_endpoint_auth_method','client_secret_basic' if client.get('client_secret') else 'none')
  if method not in ('none','client_secret_post','client_secret_basic') or method not in metadata['authorization'].get('token_endpoint_auth_methods_supported',['client_secret_basic']):raise EngineError('mcp_oauth_client_method_unsupported',422)
  if method!='none' and not isinstance(client.get('client_secret'),str):raise EngineError('mcp_oauth_client_configuration_required',422)
  client['token_endpoint_auth_method']=method
  return {k:client[k] for k in ('client_id','client_secret','token_endpoint_auth_method') if k in client}
 def start(self,principal,identifier,session_binding):
  if principal.kind!='SESSION':raise EngineError('mcp_oauth_browser_session_required',403)
  redirect=self.callback_url();self.secrets.cipher()
  with self.engine.connect() as c:
   server=self.server(c,principal,identifier);previous=self.row(c,principal.owner_id,identifier)
   previous=dict(previous) if previous else None
  metadata=discover(self.http,server['endpoint_url'],self.configured(server))
  same=previous and previous['resource_url']==server['endpoint_url'] and previous['metadata'].get('issuer')==metadata['issuer']
  client=self.client(metadata,self.configured(server),redirect,previous['client_ciphertext'] if same else None)
  state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);key=digest(state);now=now_utc()
  with self.engine.begin() as c:
   current=self.server(c,principal,identifier)
   if current['revision']!=server['revision'] or current['endpoint_url']!=server['endpoint_url']:raise EngineError('revision_conflict',409)
   row=self.row(c,principal.owner_id,identifier,True)
   values=dict(resource_url=server['endpoint_url'],server_revision=server['revision'],status='CONNECTING',metadata=metadata,
       client_ciphertext=self.seal(client),tokens_ciphertext=None,expires_at=None,active_flow=key,refresh_operation=None,error_code=None,updated_at=now)
   if row:c.execute(update(connections).where(connections.c.owner_id==principal.owner_id,connections.c.server_id==identifier).values(**values))
   else:c.execute(insert(connections).values(owner_id=principal.owner_id,server_id=identifier,**values))
   c.execute(update(flows).where(flows.c.owner_id==principal.owner_id,flows.c.expires_at<now,flows.c.used_at.is_(None)).values(secret_ciphertext=None,used_at=now))
   # Superseded flows cannot be replayed; discard their PKCE verifier.
   c.execute(update(flows).where(flows.c.owner_id==principal.owner_id,flows.c.server_id==identifier,flows.c.used_at.is_(None)).values(used_at=now,secret_ciphertext=None))
   c.execute(insert(flows).values(state_hash=key,owner_id=principal.owner_id,server_id=identifier,session_hash=digest(session_binding),
       secret_ciphertext=self.seal({'verifier':verifier,'redirect_uri':redirect}),expires_at=now+timedelta(minutes=10),used_at=None))
  endpoint=metadata['authorization']['authorization_endpoint'];p=urlsplit(endpoint)
  existing=dict(parse_qsl(p.query))
  if set(existing)&{'state','redirect_uri','client_id','response_type','code_challenge','code_challenge_method','resource','scope'}:raise EngineError('mcp_oauth_invalid_metadata',502)
  params={**existing,'response_type':'code','client_id':client['client_id'],'redirect_uri':redirect,'state':state,
      'code_challenge':b64(hashlib.sha256(verifier.encode()).digest()),'code_challenge_method':'S256','resource':metadata['resource']}
  if metadata['scope']:params['scope']=metadata['scope']
  return {'authorization_url':urlunsplit((p.scheme,p.netloc,p.path,urlencode(params),'')),'status':'CONNECTING'}
 def exchange(self,metadata,client,params):
  headers={};params={**params,'client_id':client['client_id'],'resource':metadata['resource']}
  method=client['token_endpoint_auth_method']
  if method=='client_secret_post':params['client_secret']=client['client_secret']
  elif method=='client_secret_basic':
   from urllib.parse import quote_plus
   headers['Authorization']='Basic '+base64.b64encode((quote_plus(client['client_id'])+':'+quote_plus(client['client_secret'])).encode()).decode()
  status,tokens,_=self.http.form(metadata['authorization']['token_endpoint'],params,headers)
  if status!=200:raise EngineError('mcp_oauth_token_exchange_failed',502)
  access_token=tokens.get('access_token')
  if not isinstance(access_token,str) or not 1<=len(access_token)<=16384 or any(ord(c)<33 or ord(c)>126 for c in access_token) or str(tokens.get('token_type','')).lower()!='bearer':raise EngineError('mcp_oauth_invalid_token_response',502)
  expires=tokens.get('expires_in');expires_at=None
  if expires is not None:
   if type(expires) is not int or not 1<=expires<=31536000:raise EngineError('mcp_oauth_invalid_token_response',502)
   expires_at=now_utc()+timedelta(seconds=expires)
  if 'refresh_token' in tokens and (not isinstance(tokens['refresh_token'],str) or not 1<=len(tokens['refresh_token'])<=16384):raise EngineError('mcp_oauth_invalid_token_response',502)
  return {k:tokens[k] for k in ('access_token','refresh_token','token_type','scope') if k in tokens},expires_at
 def failure(self,owner,identifier,flow,code):
  with self.engine.begin() as c:c.execute(update(connections).where(connections.c.owner_id==owner,connections.c.server_id==identifier,connections.c.active_flow==flow).values(status='ERROR',tokens_ciphertext=None,error_code=code,updated_at=now_utc()))
 def callback(self,principal,state,code,binding,error=False,response_issuer=None):
  if principal.kind!='SESSION' or not isinstance(state,str) or not 20<=len(state)<=256:raise EngineError('mcp_oauth_invalid_state',400)
  key=digest(state)
  with self.engine.begin() as c:
   flow=c.execute(select(flows).where(flows.c.state_hash==key,flows.c.owner_id==principal.owner_id).with_for_update()).mappings().first()
   if not flow or flow['used_at'] or flow['expires_at']<=now_utc() or not secrets.compare_digest(flow['session_hash'],digest(binding)):raise EngineError('mcp_oauth_invalid_state',400)
   server=self.server(c,principal,flow['server_id']);row=self.row(c,principal.owner_id,server['id'],True)
   if not row or row['active_flow']!=key or row['resource_url']!=server['endpoint_url'] or row['server_revision']!=server['revision']:raise EngineError('mcp_oauth_invalid_state',400)
   code_hash=digest(code) if isinstance(code,str) else None
   if code_hash and c.execute(select(flows.c.state_hash).where(flows.c.owner_id==principal.owner_id,flows.c.server_id==server['id'],flows.c.code_hash==code_hash)).first():raise EngineError('mcp_oauth_code_reused',400)
   payload=self.unseal(flow['secret_ciphertext']);row=dict(row)
   c.execute(update(flows).where(flows.c.state_hash==key).values(used_at=now_utc(),secret_ciphertext=None,code_hash=code_hash))
  try:
   if response_issuer is not None and response_issuer!=row['metadata']['issuer'] or row['metadata']['authorization'].get('authorization_response_iss_parameter_supported') and response_issuer is None:raise EngineError('mcp_oauth_issuer_mismatch',400)
   if error:raise EngineError('mcp_oauth_access_denied',400)
   if not isinstance(code,str) or not 1<=len(code)<=8192:raise EngineError('mcp_oauth_invalid_callback',400)
   tokens,expiry=self.exchange(row['metadata'],self.unseal(row['client_ciphertext']),{'grant_type':'authorization_code','code':code,'code_verifier':payload['verifier'],'redirect_uri':payload['redirect_uri']})
   with self.engine.begin() as c:
    current=self.server(c,principal,server['id']);connection=self.row(c,principal.owner_id,server['id'],True)
    if current['revision']!=row['server_revision'] or connection['active_flow']!=key:raise EngineError('mcp_oauth_invalid_state',400)
    c.execute(update(connections).where(connections.c.owner_id==principal.owner_id,connections.c.server_id==server['id']).values(status='CONNECTED',tokens_ciphertext=self.seal(tokens),expires_at=expiry,error_code=None,updated_at=now_utc()))
   return server['id']
  except EngineError as e:self.failure(principal.owner_id,server['id'],key,e.code);raise
 def credential(self,server,owner):
  if type(owner) is not int:raise EngineError('mcp_oauth_owner_required',403)
  with self.engine.begin() as c:
   current=MCPRepository(c).server(server['id'])
   row=self.row(c,owner,server['id'],True)
   if current['auth_type']!='oauth' or current['endpoint_url']!=server['endpoint_url'] or not row or row['resource_url']!=current['endpoint_url'] or row['status']!='CONNECTED' or not row['tokens_ciphertext']:
    raise EngineError('mcp_oauth_not_connected',409)
   row=dict(row);tokens=self.unseal(row['tokens_ciphertext'])
   if row['expires_at'] is None or row['expires_at']>now_utc()+timedelta(seconds=30):return tokens['access_token']
   refresh=tokens.get('refresh_token')
   if not refresh:raise EngineError('mcp_oauth_reconnect_required',409)
   operation=secrets.token_hex(32)
   c.execute(update(connections).where(connections.c.owner_id==owner,connections.c.server_id==server['id']).values(status='REFRESHING',refresh_operation=operation,updated_at=now_utc()))
  try:
   new,expiry=self.exchange(row['metadata'],self.unseal(row['client_ciphertext']),{'grant_type':'refresh_token','refresh_token':refresh})
   if not new.get('refresh_token'):new['refresh_token']=refresh
   with self.engine.begin() as c:
    current=MCPRepository(c).server(server['id']);connection=self.row(c,owner,server['id'],True)
    if not connection or connection['refresh_operation']!=operation or current['endpoint_url']!=row['resource_url']:raise EngineError('mcp_oauth_reconnect_required',409)
    c.execute(update(connections).where(connections.c.owner_id==owner,connections.c.server_id==server['id']).values(status='CONNECTED',tokens_ciphertext=self.seal(new),expires_at=expiry,refresh_operation=None,error_code=None,updated_at=now_utc()))
   return new['access_token']
  except EngineError:
   # Never replay a refresh token when its external exchange may have succeeded.
   with self.engine.begin() as c:c.execute(update(connections).where(connections.c.owner_id==owner,connections.c.server_id==server['id'],connections.c.refresh_operation==operation).values(status='ERROR',tokens_ciphertext=None,refresh_operation=None,error_code='mcp_oauth_reconnect_required',updated_at=now_utc()))
   raise EngineError('mcp_oauth_reconnect_required',409) from None
 def disconnect(self,principal,identifier):
  with self.engine.begin() as c:
   self.server(c,principal,identifier);row=self.row(c,principal.owner_id,identifier,True);row=dict(row) if row else None
   c.execute(update(connections).where(connections.c.owner_id==principal.owner_id,connections.c.server_id==identifier).values(status='DISCONNECTED',tokens_ciphertext=None,client_ciphertext=None,active_flow=None,refresh_operation=None,expires_at=None,error_code=None,updated_at=now_utc()))
   c.execute(update(flows).where(flows.c.owner_id==principal.owner_id,flows.c.server_id==identifier).values(secret_ciphertext=None,used_at=now_utc()))
  revoked=False
  if row and row['tokens_ciphertext'] and row['metadata']['authorization'].get('revocation_endpoint'):
   try:
    token=self.unseal(row['tokens_ciphertext']);client=self.unseal(row['client_ciphertext'])
    params={'token':token.get('refresh_token') or token['access_token'],'client_id':client['client_id']}
    headers={};method=client['token_endpoint_auth_method']
    if method=='client_secret_post':params['client_secret']=client['client_secret']
    elif method=='client_secret_basic':
     from urllib.parse import quote_plus
     headers['Authorization']='Basic '+base64.b64encode((quote_plus(client['client_id'])+':'+quote_plus(client['client_secret'])).encode()).decode()
    status,_,_=self.http.form(row['metadata']['authorization']['revocation_endpoint'],params,headers);revoked=status==200
   except EngineError:pass
  return {'status':'DISCONNECTED','connected':False,'provider_revocation_confirmed':revoked}
