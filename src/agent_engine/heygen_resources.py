"""Bounded, demand-driven HeyGen resource selection; no generation requests."""
import re
from .errors import EngineError


def resource_id(value):
 if value in ('', 'auto', None):return ''
 if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',value):
  raise EngineError('VIDEO_RESOURCE_ID_INVALID',422)
 return value


def catalog(request,path,params=None,*,accept=None):
 """Stop at the first compatible row when selecting; never pretend a scan is complete."""
 rows=[];seen=set();params=dict(params or {})
 for _ in range(10):
  response=request(path,params)
  data=response.get('data')
  if isinstance(data,dict):data=data.get('items',data.get('avatars' if path.endswith('looks') else 'voices'))
  if not isinstance(data,list):raise EngineError('VIDEO_CATALOG_INVALID',502)
  if accept is not None:
   for row in data:
    if isinstance(row,dict) and accept(row):return [row]
  else:rows.extend(data)
  if not response.get('has_more'):return [] if accept is not None else rows
  token=response.get('next_token')
  if not isinstance(token,str) or not token or token in seen:raise EngineError('VIDEO_CATALOG_PAGINATION_LOOP',502)
  seen.add(token);params={**params,'token':token}
 raise EngineError('VIDEO_CATALOG_SEARCH_LIMIT' if accept is not None else 'VIDEO_CATALOG_PAGE_LIMIT',409)


def resolve_resource(request,key,selected,language):
 from .video_worker import select_resource
 selected=resource_id(selected)
 path='/v3/avatars/looks' if key=='avatar_id' else '/v3/models/audio/voices'
 unavailable='VIDEO_AVATAR_UNAVAILABLE' if key=='avatar_id' else 'VIDEO_VOICE_UNAVAILABLE'
 if selected:
  # Fixed, documented detail endpoints; IDs can never become URLs or path segments.
  try:data=request(path+'/'+selected,None).get('data')
  except EngineError as error:
   if error.code=='VIDEO_RESOURCE_NOT_FOUND':raise EngineError(unavailable,409) from None
   raise
  if not isinstance(data,dict):raise EngineError('VIDEO_CATALOG_INVALID',502)
  identifier=select_resource([data],key,selected,language if key=='voice_id' else None)
  return identifier,data
 # Public first: a large private library cannot hide a usable public preset.
 # Public voices are filtered by the provider for the requested language, including multilingual voices.
 queries=({'ownership':'public','limit':20},{'ownership':'private','limit':20}) if key=='avatar_id' else (
  {'type':'public','language':language,'limit':20},{'type':'private','limit':20})
 incomplete=False
 for params in queries:
  def accept(row):
   try:select_resource([row],key,'',language if key=='voice_id' and params['type']=='private' else None);return True
   except EngineError:return False
  try:rows=catalog(request,path,params,accept=accept)
  except EngineError as error:
   if error.code!='VIDEO_CATALOG_SEARCH_LIMIT':raise
   incomplete=True;continue
  if rows:return select_resource(rows,key,''),rows[0]
 if incomplete:raise EngineError('VIDEO_CATALOG_SEARCH_LIMIT',409)
 raise EngineError(unavailable,409)


def resources(request,language,avatar_id='',voice_id=''):
 from .video_worker import voice_settings
 # Reject invalid identifiers before any network request.
 avatar_id=resource_id(avatar_id);voice_id=resource_id(voice_id)
 errors=[];choices={}
 for key,selected in [('avatar_id',avatar_id),('voice_id',voice_id)]:
  try:
   identifier,row=resolve_resource(request,key,selected,language)
   choices[key]=[{'id':identifier,'name':str(row.get('name') or identifier)[:200]}]
  except EngineError as error:
   if error.code not in ('VIDEO_AVATAR_UNAVAILABLE','VIDEO_VOICE_UNAVAILABLE','VIDEO_CATALOG_SEARCH_LIMIT','VIDEO_CATALOG_PAGINATION_LOOP'):raise
   errors.append(error.code);choices[key]=[]
 capabilities=request('/v3/videos/voice-capabilities',None).get('data')
 try:settings=voice_settings(capabilities,language)
 except EngineError as error:errors.append(error.code);settings=None
 return {'avatars':choices['avatar_id'],'voices':choices['voice_id'],'language':language,
         'voice_settings':settings,'errors':list(dict.fromkeys(errors)),'ready':not errors,
         'catalog_complete':False,'selection_mode':'required_resources','submitted':False}
