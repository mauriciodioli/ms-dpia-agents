"""Existing logs table and bounded activity recording; no schema creation or migration."""
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, insert
from utils.db import db

logs = Blueprint('logs', __name__)

class Logs(db.Model):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)
    userCuenta = Column(String(120)) 
    accountCuenta = Column(String(120))    
    fecha_log = Column(DateTime)  # ✅ Corrección en el tipo de dato
    ip = Column(String(120))   
    funcion = Column(String(120))   
    archivo = Column(String(120))   
    linea = Column(Integer) 
    error = Column(String(120))   
    codigoPostal = Column(String(120))
    latitude = Column(String(120))
    longitude = Column(String(120))
    language = Column(String(50))
    path = Column(String(500))
    method = Column(String(20))
    user_agent = Column(Text)
    referer = Column(String(1000))
    es_bot = Column(Boolean)
    status_code = Column(Integer)
    request_type = Column(String(50))
    trafico_sospechoso = Column(Boolean)
    motivo_sospecha = Column(String(50))
    duracion_ms = Column(Integer)
    
    def __init__(self, user_id=None, userCuenta=None, accountCuenta=None, fecha_log=None, ip=None,
                 funcion=None, archivo=None, linea=None, error=None, codigoPostal=None,
                 latitude=None, longitude=None, language=None, path=None, method=None,
                 user_agent=None, referer=None, es_bot=None, status_code=None,
                 request_type=None, trafico_sospechoso=None, motivo_sospecha=None, duracion_ms=None):
        self.user_id = user_id
        self.userCuenta = userCuenta
        self.accountCuenta = accountCuenta
        self.fecha_log = fecha_log
        self.ip = ip
        self.funcion = funcion
        self.archivo = archivo
        self.linea = linea
        self.error = error
        self.codigoPostal = codigoPostal
        self.latitude = latitude
        self.longitude = longitude
        self.language = language
        self.path = path
        self.method = method
        self.user_agent = user_agent
        self.referer = referer
        self.es_bot = es_bot
        self.status_code = status_code
        self.request_type = request_type
        self.trafico_sospechoso = trafico_sospechoso
        self.motivo_sospecha = motivo_sospecha
        self.duracion_ms = duracion_ms
    

VIEWS = {'onboard', 'home', 'mapPage', 'consultPage', 'creditsPage', 'accountPage', 'agentPage'}
EVENTS = {'session_start', 'page_view', 'heartbeat', 'visibility', 'page_exit'}


def clean_url(value, limit):
    """Never store URL query parameters or fragments (credentials, searches, email)."""
    try:
        parsed = urlsplit(str(value or ''))
        # Drop userinfo too. Referrer is informational, never a trusted origin.
        host = parsed.hostname or ''
        return urlunsplit((parsed.scheme if parsed.scheme in ('http','https') else '', host,
                           parsed.path, '', ''))[:limit] or None
    except ValueError:
        return None


def client_ip():
    remote = request.remote_addr or ''
    trusted = current_app.config.get('ACTIVITY_TRUSTED_PROXIES', '')
    try:
        networks = [ip_network(value.strip()) for value in trusted.split(',') if value.strip()]
        if any(ip_address(remote) in network for network in networks):
            # Trust only explicitly configured reverse proxies, never arbitrary headers.
            forwarded = request.headers.get('X-Real-IP', '')
            if forwarded:
                return str(ip_address(forwarded.strip()))
    except ValueError:
        pass
    return remote[:120] or None


def visitor_id():
    if 'activity_visitor' not in session:
        session['activity_visitor'] = str(uuid4())
    return session['activity_visitor']


def base_values():
    ua = request.headers.get('User-Agent', '')[:2048]
    suspicious = any(marker in request.path.lower() for marker in ('/.env','/.git','wp-admin','wp-login','phpmyadmin','../'))
    return dict(user_id=session.get('user_id') if type(session.get('user_id')) is int else None,
                userCuenta=visitor_id(), fecha_log=datetime.now(timezone.utc).replace(tzinfo=None),
                ip=client_ip(), path=request.path[:500], method=request.method[:20],
                user_agent=ua or None, referer=clean_url(request.headers.get('Referer'),1000),
                language=request.accept_languages.best[:50] if request.accept_languages.best else None,
                latitude=None, longitude=None, es_bot=any(marker in ua.lower() for marker in
                    ('bot','crawler','spider','headless','scanner','sqlmap')),
                trafico_sospechoso=suspicious, motivo_sospecha='suspicious_path' if suspicious else None)


def write_log(values):
    # Central guard applies to both HTTP requests and browser activity events.
    if values.get('ip') == '127.0.0.1':
        return True
    try:
        # Independent transaction: never commits or rolls back business data.
        with db.engine.begin() as conn:
            conn.execute(insert(Logs.__table__).values(**values))
        return True
    except Exception:
        # Do not log SQL parameters, IPs, session contents or database credentials.
        current_app.logger.warning('Activity recording unavailable')
        return False


@logs.post('/api/activity')
def browser_activity():
    if not current_app.config.get('ACTIVITY_LOGGING_ENABLED',True):
        return '',204
    origin=request.headers.get('Origin')
    if request.headers.get('Sec-Fetch-Site')=='cross-site' or (origin and urlsplit(origin).netloc!=request.host):
        return jsonify(success=False),403
    if not request.is_json or (request.content_length or 0)>2048:
        return jsonify(success=False),400
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or set(data)-{'event','view','duration_ms','session_id','language','postal_code'}:
        return jsonify(success=False),400
    event,view=data.get('event'),data.get('view')
    duration=data.get('duration_ms')
    if not isinstance(event,str) or event not in EVENTS or not isinstance(view,str) or view not in VIEWS or type(duration) is not int or not 0<=duration<=86400000:
        return jsonify(success=False),400
    try:
        account=str(UUID(data.get('session_id','')))
    except (ValueError,TypeError,AttributeError):
        return jsonify(success=False),400
    language=data.get('language');postal=data.get('postal_code')
    if (language is not None and (not isinstance(language,str) or len(language)>50)) or (postal is not None and (not isinstance(postal,str) or len(postal)>120)):
        return jsonify(success=False),400
    values=base_values()
    values.update(accountCuenta=account,funcion='main.index:'+view+':'+event,
                  archivo='activity-tracker.js',status_code=200,request_type='browser_activity',
                  duracion_ms=duration,language=language or values['language'],codigoPostal=postal)
    # Browser duration, view, language and postal selection are self-reported analytics.
    return ('',204) if write_log(values) else (jsonify(success=False),503)


def init_request_logging(app):
    if app.extensions.get('activity_logging'):
        return
    app.extensions['activity_logging']=True

    @app.before_request
    def activity_start():
        g.activity_started=perf_counter()

    @app.after_request
    def activity_finish(response):
        if not app.config.get('ACTIVITY_LOGGING_ENABLED',True) or request.path.startswith('/static/') or request.endpoint=='logs.browser_activity' or request.method=='OPTIONS':
            return response
        values=base_values()
        handler=app.view_functions.get(request.endpoint)
        code=getattr(handler,'__code__',None)
        values.update(funcion=(request.endpoint or 'not_found')[:120],archivo=code.co_filename.replace('\\','/').rsplit('/',1)[-1][:120] if code else None,
                      linea=code.co_firstlineno if code else None,
                      status_code=response.status_code,error='HTTP '+str(response.status_code) if response.status_code>=400 else None,
                      request_type='api' if request.path.startswith('/api/') else 'page',
                      duracion_ms=max(0,round((perf_counter()-getattr(g,'activity_started',perf_counter()))*1000)))
        write_log(values)
        return response
