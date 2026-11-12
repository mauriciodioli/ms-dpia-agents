"""Bounded Streamable HTTP MCP client. Pinned public DNS, TLS, no redirects/proxies."""
import http.client
import ipaddress
import json
import queue
import re
import socket
import ssl
import time
from contextlib import contextmanager
from threading import Thread, Timer
from urllib.parse import urlsplit
from uuid import uuid4
from .errors import EngineError

VERSION='2025-06-18'
MAX_BYTES=1048576


def validate_url(value):
    try:
        if not isinstance(value,str) or len(value)>2048 or any(ord(c)<33 or ord(c)>126 for c in value):raise ValueError()
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.port not in (None,443) or p.username or p.password or p.query or p.fragment:raise ValueError()
        host=p.hostname.encode('idna').decode('ascii').lower()
        if not re.fullmatch(r'[a-z0-9.-]+',host) or host.endswith('.') or host in ('localhost','metadata.google.internal'):raise ValueError()
        try:
            ip=ipaddress.ip_address(host)
        except ValueError:ip=None
        if ip and not ip.is_global:raise ValueError()
        return 'https://'+host+(p.path or '/mcp')
    except (ValueError,UnicodeError,TypeError,AttributeError):
        raise EngineError('mcp_invalid_url',422) from None


def public_addresses(host, timeout=5):
    result=queue.Queue(maxsize=1)
    def resolve():
        try:result.put(socket.getaddrinfo(host,443,type=socket.SOCK_STREAM))
        except OSError:result.put(None)
    Thread(target=resolve,daemon=True).start()
    try:rows=result.get(timeout=timeout)
    except queue.Empty:raise EngineError('mcp_dns_timeout',502) from None
    addresses=list(dict.fromkeys(row[4][0] for row in rows or []))
    if not addresses:raise EngineError('mcp_dns_failed',502)
    if any(not ipaddress.ip_address(addr).is_global for addr in addresses):raise EngineError('mcp_ssrf_blocked',422)
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host,443,timeout=timeout,context=ssl.create_default_context())
        self.address=address

    def connect(self):
        self.sock=socket.create_connection((self.address,443),timeout=self.timeout)
        self.sock=self._context.wrap_socket(self.sock,server_hostname=self.host)


class SafeHTTP:
    def __init__(self, url, timeout):
        self.url=validate_url(url)
        self.deadline=time.monotonic()+timeout
        self.host=urlsplit(self.url).hostname
        self.address=public_addresses(self.host,min(5,timeout))[0]

    def post(self, headers, body, notification=False):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise EngineError('mcp_timeout',502)
        connection=PinnedHTTPS(self.host,self.address,min(remaining,10))
        def abort():
            if connection.sock:
                try:connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            connection.close()
        timer=Timer(remaining,abort);timer.daemon=True;timer.start()
        try:
            connection.request('POST',urlsplit(self.url).path or '/',body=json.dumps(body,allow_nan=False).encode(),headers=headers)
            response=connection.getresponse()
            if notification:
                if response.status not in (200,202,204):raise EngineError('mcp_protocol_error',502)
                return {},{}
            if response.status!=200:raise EngineError('mcp_upstream_error',502)
            content_type=response.getheader('Content-Type','').split(';')[0].strip().lower()
            if content_type not in ('application/json','text/event-stream'):raise EngineError('mcp_invalid_response',502)
            payload=bytearray()
            while True:
                remaining=self.deadline-time.monotonic()
                if remaining<=0:raise EngineError('mcp_timeout',502)
                if connection.sock:connection.sock.settimeout(remaining)
                chunk=response.read1(16384)
                if not chunk:break
                payload.extend(chunk)
                if len(payload)>MAX_BYTES:raise EngineError('mcp_response_limit',502)
                if content_type=='text/event-stream':
                    normalized=bytes(payload).replace(b'\r\n',b'\n')
                    while b'\n\n' in normalized:
                        event,normalized=normalized.split(b'\n\n',1)
                        data=b'\n'.join(line[5:].lstrip(b' ') for line in event.split(b'\n') if line.startswith(b'data:'))
                        if data:
                            parsed=json.loads(data)
                            if isinstance(parsed,dict) and parsed.get('id')==body.get('id'):
                                return parsed,{'session':response.getheader('Mcp-Session-Id')}
                    # Keep the whole bounded buffer to parse complete events consistently.
            if content_type!='application/json':raise EngineError('mcp_invalid_response',502)
            return json.loads(payload),{'session':response.getheader('Mcp-Session-Id')}
        except (socket.timeout,TimeoutError):raise EngineError('mcp_timeout',502) from None
        except (OSError,http.client.HTTPException,ValueError,UnicodeError):raise EngineError('mcp_transport_error',502) from None
        finally:timer.cancel();connection.close()


class MCPClient:
    def __init__(self, server, credential=None, *, http_factory=SafeHTTP):
        self.server=server
        self.http=http_factory(server['endpoint_url'],server['timeout_seconds'])
        self.session_id=None
        self.version=None
        self.headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json'}
        if server['auth_type']=='bearer':self.headers['Authorization']='Bearer '+credential
        elif server['auth_type']=='header':self.headers[credential['name']]=credential['value']

    def rpc(self, method, params=None, *, notification=False):
        body={'jsonrpc':'2.0','method':method}
        if params is not None:body['params']=params
        if not notification:body['id']=str(uuid4())
        headers=dict(self.headers)
        if self.session_id:headers['Mcp-Session-Id']=self.session_id
        if self.version:headers['MCP-Protocol-Version']=self.version
        result,meta=self.http.post(headers,body,notification)
        session=meta.get('session')
        if session is not None:
            if not isinstance(session,str) or not 1<=len(session)<=256 or any(ord(c)<33 or ord(c)>126 for c in session):raise EngineError('mcp_invalid_response',502)
            if self.session_id and self.session_id!=session:raise EngineError('mcp_session_changed',502)
            self.session_id=session
        if notification:return {}
        if (not isinstance(result,dict) or result.get('jsonrpc')!='2.0' or result.get('id')!=body['id']
                or 'error' in result or not isinstance(result.get('result'),dict)):
            raise EngineError('mcp_protocol_error',502)
        return result['result']

    def initialize(self):
        result=self.rpc('initialize',{'protocolVersion':VERSION,'capabilities':{},'clientInfo':{'name':'DPIA Agents','version':'1.0'}})
        if result.get('protocolVersion')!=VERSION or not isinstance(result.get('capabilities'),dict) or 'tools' not in result['capabilities']:
            raise EngineError('mcp_unsupported_protocol',502)
        self.version=VERSION
        self.rpc('notifications/initialized',notification=True)
        return self

    def discover(self):
        tools=[];cursor=None;seen=set()
        for _ in range(20):
            result=self.rpc('tools/list',{'cursor':cursor} if cursor else {})
            if not isinstance(result.get('tools'),list):raise EngineError('mcp_invalid_response',502)
            tools.extend(result['tools'])
            if len(tools)>200:raise EngineError('mcp_tool_limit',502)
            cursor=result.get('nextCursor')
            if not cursor:return tools
            if not isinstance(cursor,str) or len(cursor)>2048 or cursor in seen:raise EngineError('mcp_invalid_cursor',502)
            seen.add(cursor)
        raise EngineError('mcp_tool_limit',502)

    def call(self, name, arguments, *, before_call):
        before_call()
        result=self.rpc('tools/call',{'name':name,'arguments':arguments})
        if result.get('isError'):raise EngineError('mcp_tool_error',502)
        if not isinstance(result.get('content'),list):raise EngineError('mcp_invalid_response',502)
        return result
