"""Small OAuth HTTP transport reusing pinned public DNS and TLS. Never redirects."""
import json,socket,http.client,time
from threading import Timer
from urllib.parse import urlsplit,urlencode
from ..mcp_transport import validate_url,public_addresses,PinnedHTTPS
from ..errors import EngineError


def secure_url(url,*,query=False):
    if not isinstance(url,str):raise EngineError('mcp_oauth_invalid_metadata',502)
    p=urlsplit(url)
    if p.fragment or (p.query and not query):raise EngineError('mcp_oauth_invalid_metadata',502)
    validate_url(url.split('?',1)[0])
    return url

class OAuthHTTP:
    def request(self,method,url,body=None,headers=None):
        secure_url(url,query=method=='GET');p=urlsplit(url)
        address=public_addresses(p.hostname,5)[0]
        conn=PinnedHTTPS(p.hostname,address,10)
        def abort():
            if conn.sock:
                try:conn.sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            conn.close()
        timer=Timer(15,abort);timer.daemon=True;timer.start()
        try:
            conn.request(method,(p.path or '/')+('?' +p.query if p.query else ''),body=body,headers=headers or {'Accept':'application/json'})
            response=conn.getresponse();raw=response.read(262145)
            if len(raw)>262144:raise EngineError('mcp_oauth_response_limit',502)
            info={'www-authenticate':response.getheader('WWW-Authenticate','')}
            try:data=json.loads(raw) if raw else {}
            except (ValueError,UnicodeError):data={}
            if not isinstance(data,dict):raise EngineError('mcp_oauth_invalid_response',502)
            return response.status,data,info
        except (OSError,ValueError,http.client.HTTPException):raise EngineError('mcp_oauth_transport_error',502) from None
        finally:timer.cancel();conn.close()
    def get(self,url):return self.request('GET',url)
    def form(self,url,body,headers=None):return self.request('POST',url,urlencode(body).encode(),{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded',**(headers or {})})
    def register(self,url,body):return self.request('POST',url,json.dumps(body,allow_nan=False).encode(),{'Accept':'application/json','Content-Type':'application/json'})
