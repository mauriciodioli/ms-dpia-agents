"""Read-only REST transport with pinned public DNS/TLS and no redirects/proxies."""
import json,socket,http.client
from threading import Timer
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
 def get(self,base,path,key,header,timeout):
  base=base_url(base)
  if not isinstance(path,str) or not path.startswith('/v3/') or any(c in path for c in ('?','#','\\','\r','\n')):raise EngineError('rest_operation_not_allowed',403)
  host=urlsplit(base).hostname;address=public_addresses(host,min(timeout,5))[0]
  conn=PinnedHTTPS(host,address,min(timeout,10))
  def abort():
   if conn.sock:
    try:conn.sock.shutdown(socket.SHUT_RDWR)
    except OSError:pass
   conn.close()
  timer=Timer(timeout,abort);timer.daemon=True;timer.start()
  try:
   conn.request('GET',path,headers={'Accept':'application/json',header:key})
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
