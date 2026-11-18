"""Read-only REST transport with pinned public DNS/TLS and no redirects/proxies."""
import json,socket,http.client
from threading import Timer,Event
from urllib.parse import urlsplit
from ..mcp_transport import validate_url,public_addresses,PinnedHTTPS
from ..errors import EngineError

def base_url(value):
 if not isinstance(value,str):raise EngineError('rest_invalid_url',422)
 try:
  parsed=urlsplit(value)
  if parsed.path not in ('','/') or parsed.query or parsed.fragment:raise ValueError()
  return 'https://'+urlsplit(validate_url(value)).netloc
 except (ValueError,EngineError):raise EngineError('rest_invalid_url',422) from None

class RESTHTTP:
 def get(self,base,path,key,header,timeout,params=None):
  if params is not None:
   from urllib.parse import urlencode
   if path not in ('/v3/models/audio/voices','/v3/avatars/looks') or set(params)-{'type','language','token','limit','ownership'}:raise EngineError('rest_operation_not_allowed',403)
   if any(not isinstance(v,(str,int)) for v in params.values()):raise EngineError('rest_operation_not_allowed',403)
   return self._request(base,path,key,header,timeout,query=urlencode(params))
  return self._request(base,path,key,header,timeout)
 def post_video(self,base,key,timeout,body,operation,before_send=None):
  import re
  from ..provider_transport import serialize_body
  if not isinstance(operation,str) or not re.fullmatch(r'[A-Za-z0-9_:.-]{1,255}',operation):raise EngineError('rest_operation_not_allowed',403)
  return self._request(base,'/v3/videos',key,'X-Api-Key',timeout,serialize_body(body),operation,before_send=before_send)
 def _request(self,base,path,key,header,timeout,body=None,operation=None,query=None,before_send=None):
  base=base_url(base)
  if not isinstance(path,str) or not path.startswith('/v3/') or any(c in path for c in ('?','#','\\','\r','\n')):raise EngineError('rest_operation_not_allowed',403)
  host=urlsplit(base).hostname;address=public_addresses(host,min(timeout,5))[0]
  conn=PinnedHTTPS(host,address,min(timeout,10))
  expired=Event()
  def abort():
   expired.set()
   if conn.sock:
    try:conn.sock.shutdown(socket.SHUT_RDWR)
    except OSError:pass
   conn.close()
  timer=Timer(timeout,abort);timer.daemon=True;timer.start()
  try:
   headers={'Accept':'application/json',header:key}
   if body is not None:headers.update({'Content-Type':'application/json','Idempotency-Key':operation})
   from ..errors import ProviderNotSent
   try:
    if before_send is not None:before_send()
    if expired.is_set():raise EngineError('VIDEO_PROVIDER_NOT_SENT',504)
   except EngineError as error:raise ProviderNotSent(error.code,error.status) from None
   except Exception:raise ProviderNotSent('VIDEO_PROVIDER_NOT_SENT',502) from None
   conn.request('POST' if body is not None else 'GET',path+('?' + query if query else ''),body=body,headers=headers)
   response=conn.getresponse()
   if 300<=response.status<400:raise EngineError('rest_redirect_blocked',502)
   raw=response.read(1048577)
   if len(raw)>1048576:raise EngineError('rest_response_limit',502)
   if response.status!=200:return response.status,{}
   try:data=json.loads(raw) if raw else {}
   except (ValueError,UnicodeError):raise EngineError('rest_invalid_response',502) from None
   if not isinstance(data,dict):raise EngineError('rest_invalid_response',502)
   return response.status,data
  except (socket.timeout,TimeoutError):raise EngineError('rest_timeout',504) from None
  except (OSError,http.client.HTTPException):raise EngineError('rest_transport_error',502) from None
  finally:timer.cancel();conn.close()
