"""OAuth browser endpoints: fixed callback, existing identity/CSRF permissions."""
import secrets,logging,re
from flask import current_app,session,request,redirect
from ..api import api,endpoint,engine,arguments,identifier,json_body
from ..mcp_api import write,service as mcp_service
from ..errors import EngineError
from .service import OAuthService,CALLBACK

def service():return current_app.extensions.get('mcp_oauth_service') or OAuthService(engine(),current_app.config)

@api.post('/mcp/servers/<server_id>/oauth/authorize')
@endpoint()
def authorize(conn,principal,repo,server_id):
 arguments();identifier(server_id);write(principal)
 if json_body()!={}:raise EngineError('invalid_contract')
 binding=session.get('mcp_oauth_binding')
 if not binding:binding=secrets.token_urlsafe(32);session['mcp_oauth_binding']=binding
 return service().start(principal,server_id,binding)

@api.get('/mcp/servers/<server_id>/oauth/status')
@endpoint()
def status(conn,principal,repo,server_id):
 arguments();return service().state(principal,identifier(server_id))

@api.post('/mcp/servers/<server_id>/oauth/disconnect')
@endpoint()
def disconnect(conn,principal,repo,server_id):
 arguments();write(principal)
 if json_body()!={}:raise EngineError('invalid_contract')
 return service().disconnect(principal,identifier(server_id))

@api.get('/mcp/oauth/callback')
@endpoint(html=True)
def callback(conn,principal,repo):
 arguments(('state','code','error','error_description','error_uri','iss'))
 if any(len(request.args.getlist(k))!=1 for k in request.args):raise EngineError('mcp_oauth_invalid_callback',400)
 # Never expose provider errors or callback secrets in the resulting URL/UI.
 server_id=service().callback(principal,request.args.get('state'),request.args.get('code'),session.get('mcp_oauth_binding',''),bool(request.args.get('error')),request.args.get('iss'))
 # Existing initialize/tools-list workflow only, never tools/call. No auto-enable.
 with engine().connect() as c:
  from ..mcp_repository import MCPRepository
  row=MCPRepository(c).server(server_id,principal)
 mcp_service().probe(principal,server_id,{'expected_revision':row['revision']},discover=True)
 response=redirect('/integrations',code=303);response.headers['Referrer-Policy']='no-referrer';return response

class CallbackLogFilter(logging.Filter):
 """Sanitize common in-process access log request-lines; proxy config is separate."""
 def filter(self,record):
  def clean(value):
   if not isinstance(value,str):return value
   return re.sub(r'(/api/agents/v1/mcp/oauth/callback)\?[^\s"\x1b]*',r'\1?[redacted]',value)
  record.msg=clean(record.msg)
  if isinstance(record.args,tuple):record.args=tuple(clean(v) for v in record.args)
  elif isinstance(record.args,dict):record.args={k:clean(v) for k,v in record.args.items()}
  return True

for name in ('werkzeug','gunicorn.access'):
 logging.getLogger(name).addFilter(CallbackLogFilter())

@api.after_request
def oauth_referrer_policy(response):
 if request.path==CALLBACK:response.headers['Referrer-Policy']='no-referrer'
 return response
