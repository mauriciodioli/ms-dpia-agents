"""Owner-scoped REST administration. Network always outside SQL transactions."""
import json
from uuid import uuid4
from sqlalchemy import select,insert,update,inspect
from ..auth import active_user,ADMIN_ROLES,now_utc
from ..contracts import iso
from ..integrations import IntegrationService
from ..errors import EngineError
from .models import providers
from .adapters import adapter,ADAPTERS
from .transport import base_url,RESTHTTP

PRIVILEGED=ADMIN_ROLES|{'advanced','avanzado'}

def access(conn,principal,scope):
 principal.require(scope)
 if str(active_user(conn,principal.owner_id)['roll']).strip().casefold() not in PRIVILEGED:raise EngineError('rest_role_required',403)

def public(row):
 return {k:row[k] for k in ('id','adapter','name','description','base_url','auth_type','auth_header','enabled','timeout_seconds','revision','health','error_code','http_status')}|{'has_credential':bool(row['credential_ciphertext']),'credential_bound':bool(row['credential_ciphertext']) and row['credential_origin']==row['base_url'],**{k:iso(row[k]) for k in ('checked_at','created_at','updated_at')}}

class Service:
 def __init__(self,engine,config,http=None):self.engine,self.config=engine,config;self.secrets=IntegrationService(engine,config);self.http=http or RESTHTTP()
 def row(self,conn,principal,identifier,lock=False):
  if not inspect(conn).has_table(providers.name):raise EngineError('rest_storage_not_initialized',503)
  q=select(providers).where(providers.c.id==identifier,providers.c.owner_id==principal.owner_id)
  row=conn.execute(q.with_for_update() if lock else q).mappings().first()
  if row is None:raise EngineError('rest_provider_not_found',404)
  return row
 def listing(self,principal):
  with self.engine.connect() as c:
   access(c,principal,'rest:read')
   if not inspect(c).has_table(providers.name):raise EngineError('rest_storage_not_initialized',503)
   rows=c.execute(select(providers).where(providers.c.owner_id==principal.owner_id).order_by(providers.c.created_at.desc(),providers.c.id).limit(100)).mappings()
   return {'items':[public(r) for r in rows],'adapters':[{'id':a.id,'name':a.name,'base_url':a.base_url,'auth_header':a.header} for a in ADAPTERS.values()]}
 def detail(self,principal,identifier):
  with self.engine.connect() as c:access(c,principal,'rest:read');return public(self.row(c,principal,identifier))
 def encrypt(self,key):
  if not isinstance(key,str) or not 1<=len(key)<=8192 or any(ord(x)<33 or ord(x)>126 for x in key):raise EngineError('rest_invalid_credential',422)
  return self.secrets.cipher().encrypt(json.dumps(key).encode()).decode()
 def save(self,principal,body,identifier=None):
  allowed={'adapter','name','description','base_url','timeout_seconds','credential','expected_revision'}
  if not isinstance(body,dict) or set(body)-allowed or not {'adapter','name','base_url','timeout_seconds'}<=set(body):raise EngineError('invalid_contract')
  spec=adapter(body['adapter']);url=base_url(body['base_url']);name=body['name'];description=body.get('description','')
  if not isinstance(name,str) or not 1<=len(name.strip())<=150 or not isinstance(description,str) or len(description)>4000 or type(body['timeout_seconds']) is not int or not 1<=body['timeout_seconds']<=120:raise EngineError('invalid_contract')
  with self.engine.begin() as c:
   access(c,principal,'rest:write');old=self.row(c,principal,identifier,True) if identifier else None
   if old and (type(body.get('expected_revision')) is not int or body['expected_revision']!=old['revision']):raise EngineError('revision_conflict',409)
   if old and old['adapter']!=spec.id:raise EngineError('rest_adapter_change_forbidden',422)
   encrypted=old['credential_ciphertext'] if old else None;bound=old['credential_origin'] if old else None
   if body.get('credential') not in (None,''):encrypted=self.encrypt(body['credential']);bound=url
   now=now_utc();values=dict(adapter=spec.id,name=name.strip(),description=description,base_url=url,auth_type='api_key',auth_header=spec.header,timeout_seconds=body['timeout_seconds'],credential_ciphertext=encrypted,credential_origin=bound,enabled=False,health='UNKNOWN',error_code=None,http_status=None,checked_at=None,updated_at=now)
   if old:c.execute(update(providers).where(providers.c.id==identifier,providers.c.owner_id==principal.owner_id).values(**values,revision=old['revision']+1))
   else:identifier=str(uuid4());c.execute(insert(providers).values(id=identifier,owner_id=principal.owner_id,created_at=now,revision=1,**values))
   return public(self.row(c,principal,identifier))
 def mutate(self,principal,identifier,body,disconnect=False):
  expected={'expected_revision'} if disconnect else {'expected_revision','enabled'}
  if not isinstance(body,dict) or set(body)!=expected or type(body.get('expected_revision')) is not int or (not disconnect and type(body.get('enabled')) is not bool):raise EngineError('invalid_contract')
  with self.engine.begin() as c:
   access(c,principal,'rest:write');row=self.row(c,principal,identifier,True)
   if row['revision']!=body['expected_revision']:raise EngineError('revision_conflict',409)
   values=dict(enabled=False if disconnect else body['enabled'],updated_at=now_utc(),revision=row['revision']+1)
   if disconnect:values.update(credential_ciphertext=None,credential_origin=None,health='DISCONNECTED',error_code=None,http_status=None,checked_at=None)
   elif body['enabled'] and (row['health']!='HEALTHY' or not row['credential_ciphertext'] or row['credential_origin']!=row['base_url']):raise EngineError('rest_provider_not_ready',409)
   c.execute(update(providers).where(providers.c.id==identifier,providers.c.owner_id==principal.owner_id).values(**values));return public(self.row(c,principal,identifier))
 def credential(self,principal,identifier,body):
  if not isinstance(body,dict) or set(body)!={'expected_revision','credential'} or type(body['expected_revision']) is not int:raise EngineError('invalid_contract')
  with self.engine.begin() as c:
   access(c,principal,'rest:write');row=self.row(c,principal,identifier,True)
   if row['revision']!=body['expected_revision']:raise EngineError('revision_conflict',409)
   encrypted=self.encrypt(body['credential'])
   c.execute(update(providers).where(providers.c.id==identifier,providers.c.owner_id==principal.owner_id).values(credential_ciphertext=encrypted,credential_origin=row['base_url'],enabled=False,health='UNKNOWN',error_code=None,http_status=None,checked_at=None,revision=row['revision']+1,updated_at=now_utc()))
   return public(self.row(c,principal,identifier))
 def operations(self,principal,identifier):
  row=self.detail(principal,identifier);return {'items':[{'id':k,**v} for k,v in adapter(row['adapter']).operations.items()]}
 def prepare(self,principal,identifier,body):
  with self.engine.connect() as c:access(c,principal,'rest:write');row=self.row(c,principal,identifier)
  return adapter(row['adapter']).prepare(body)
 def read(self,principal,identifier,operation='account',probe=False,revision=None):
  with self.engine.connect() as c:
   access(c,principal,'rest:write' if probe else 'rest:read');row=dict(self.row(c,principal,identifier))
   if probe and revision!=row['revision']:raise EngineError('revision_conflict',409)
   spec=adapter(row['adapter']);op=spec.operations.get(operation)
   if not op or not op['available'] or op['method']!='GET':raise EngineError('rest_operation_not_allowed',403)
   if not probe and not row['enabled']:raise EngineError('rest_provider_disabled',409)
   if not row['credential_ciphertext']:raise EngineError('rest_credential_required',409)
   if row['credential_origin']!=row['base_url']:raise EngineError('rest_credential_origin_changed',409)
  try:secret=json.loads(self.secrets.decrypt(row))
  except (ValueError,TypeError):raise EngineError('integration_encryption_unavailable',503) from None
  if not isinstance(secret,str):raise EngineError('integration_encryption_unavailable',503)
  error=None;status=None;data=None
  try:
   status,data=self.http.get(row['base_url'],op['path'],secret,row['auth_header'],row['timeout_seconds'])
   code={401:'rest_unauthorized',403:'rest_forbidden',429:'rest_rate_limited'}.get(status)
   if code or status>=500:raise EngineError(code or 'rest_upstream_error',502)
   if status!=200 or not isinstance(data,dict) or not isinstance(data.get('data'),(dict,list)):raise EngineError('rest_invalid_response',502)
  except EngineError as e:error=e
  with self.engine.begin() as c:
   access(c,principal,'rest:write' if probe else 'rest:read');current=self.row(c,principal,identifier,True)
   if current['revision']!=row['revision']:raise EngineError('revision_conflict',409)
   c.execute(update(providers).where(providers.c.id==identifier,providers.c.owner_id==principal.owner_id).values(health='ERROR' if error else 'HEALTHY',error_code=error.code if error else None,http_status=status,checked_at=now_utc(),revision=row['revision']+1,updated_at=now_utc(),**({'enabled':False} if error else {})))
   result=public(self.row(c,principal,identifier))
  if probe:return {'provider':result,'success':error is None}
  if error:raise error
  def redact(value):
   if isinstance(value,str):return value.replace(secret,'[redacted]')
   if isinstance(value,list):return [redact(x) for x in value]
   if isinstance(value,dict):return {k.replace(secret,'[redacted]'):redact(v) for k,v in value.items() if k.casefold() not in {'api_key','apikey','access_token','refresh_token','authorization','x-api-key'}}
   return value
  output=data['data']
  if operation=='quota':output={k:output[k] for k in ('billing_type','wallet','subscription','usage_based') if k in output} if isinstance(output,dict) else {}
  return {'operation':operation,'data':redact(output),'provider':result}
 def video_resources(self,principal,identifier,language,avatar_id='',voice_id=''):
  from ..heygen_resources import resources
  import re
  if not isinstance(language,str) or not re.fullmatch(r'[A-Za-z]{2,20}(?:-[A-Za-z0-9]{2,8})?',language):raise EngineError('invalid_contract',422)
  with self.engine.connect() as c:
   access(c,principal,'rest:read');row=dict(self.row(c,principal,identifier))
   if row['adapter']!='heygen' or not row['enabled']:raise EngineError('rest_provider_disabled',409)
   if not row['credential_ciphertext'] or row['credential_origin']!=row['base_url']:raise EngineError('rest_credential_required',409)
  secret=json.loads(self.secrets.decrypt(row))
  if not isinstance(secret,str) or not secret:raise EngineError('integration_encryption_unavailable',503)
  def request(path,params):
   status,data=self.http.get(row['base_url'],path,secret,row['auth_header'],row['timeout_seconds'],**({'params':params} if params else {}))
   if status!=200:raise EngineError({404:'VIDEO_RESOURCE_NOT_FOUND',401:'rest_unauthorized',403:'rest_forbidden',429:'rest_rate_limited'}.get(status,'rest_upstream_error'),502)
   if not isinstance(data,dict) or secret in json.dumps(data):raise EngineError('VIDEO_CATALOG_INVALID',502)
   return data
  result=resources(request,language,avatar_id,voice_id)
  with self.engine.connect() as c:
   access(c,principal,'rest:read');current=self.row(c,principal,identifier)
   if current['revision']!=row['revision']:raise EngineError('revision_conflict',409)
  return result
