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
  voice_language=data.get('language') if key=='voice_id' else None
  aliases={'es':{'es','espanol','español','spanish','multilingual'},'en':{'en','english','multilingual'},
           'pt':{'pt','portuguese','português','multilingual'}}
  if key=='voice_id' and isinstance(voice_language,str) and language.split('-')[0].lower() in aliases:
   allowed=aliases[language.split('-')[0].lower()]
   if voice_language.lower().split('-')[0] not in allowed:raise EngineError(unavailable,409)
  identifier=select_resource([data],key,selected,None)
  return identifier,data
 # Public first: a large private library cannot hide a usable public preset.
 # Public voices are filtered by the provider for the requested language, including multilingual voices.
 queries=({'ownership':'public','limit':20},{'ownership':'private','limit':20}) if key=='avatar_id' else (
  {'type':'public','limit':20},{'type':'private','limit':20})
 incomplete=False
 for params in queries:
  def accept(row):
   if key=='voice_id' and isinstance(row.get('language'),str):
    aliases={'es':{'es','spanish','español','multilingual'},'en':{'en','english','multilingual'},'pt':{'pt','portuguese','português','multilingual'}}
    allowed=aliases.get(language.split('-')[0].lower())
    if allowed and row['language'].lower().split('-')[0] not in allowed:return False
   try:select_resource([row],key,'',None);return True
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
 if avatar_id or voice_id:
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
          'voice_settings':settings,'errors':errors,'ready':not errors,'catalog_complete':False,
          'selection_mode':'required_resources','submitted':False}
 errors=[];choices={};complete=True
 from urllib.parse import urlsplit
 def url(value):
  if not isinstance(value,str):return None
  try:p=urlsplit(value)
  except ValueError:return None
  return value if p.scheme=='https' and p.hostname and not p.username and not p.password else None
 for key,path in [('avatar_id','/v3/avatars/looks'),('voice_id','/v3/models/audio/voices')]:
  result=[];ids=set();error_count=len(errors)
  try:
   for kind in ('public','private'):
    params={'ownership' if key=='avatar_id' else 'type':kind,'limit':50};seen=set()
    for _ in range(3):
     response=request(path,params);data=response.get('data')
     if isinstance(data,dict):data=data.get('items',data.get('avatars' if key=='avatar_id' else 'voices'))
     if not isinstance(data,list):raise EngineError('VIDEO_CATALOG_INVALID',502)
     for row in data:
      if not isinstance(row,dict):continue
      identifier=row.get('id') if key=='avatar_id' else row.get('voice_id') or row.get('id')
      if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',identifier) or identifier in ids:continue
      if key=='avatar_id' and ('avatar_iv' not in row.get('supported_api_engines',[]) or row.get('status','completed')!='completed'):continue
      if key=='voice_id' and row.get('status','ACTIVE') not in ('ACTIVE','active','completed'):continue
      ids.add(identifier);result.append({'id':identifier,'name':str(row.get('name') or identifier)[:200],
       'preview_image_url':url(row.get('preview_image_url') or row.get('image_url')),
       'gender':row.get('gender') if isinstance(row.get('gender'),str) else None,
       'language':row.get('language') if isinstance(row.get('language'),str) else None,
       'preview_audio_url':url(row.get('preview_audio_url') or row.get('sample_audio_url'))})
     if not response.get('has_more'):break
     token=response.get('next_token')
     if not isinstance(token,str) or not token or token in seen:raise EngineError('VIDEO_CATALOG_PAGINATION_LOOP',502)
     seen.add(token);params={**params,'token':token}
    else:complete=False
  except EngineError as error:
   errors.append(error.code);complete=False
  choices[key]=result
  if not result and len(errors)==error_count:errors.append('VIDEO_AVATAR_UNAVAILABLE' if key=='avatar_id' else 'VIDEO_VOICE_UNAVAILABLE')
 capabilities=request('/v3/videos/voice-capabilities',None).get('data')
 try:settings=voice_settings(capabilities,language)
 except EngineError as error:errors.append(error.code);settings=None
 return {'avatars':choices['avatar_id'],'voices':choices['voice_id'],'language':language,
         'voice_settings':settings,'errors':list(dict.fromkeys(errors)),'ready':not errors,
         'catalog_complete':complete,'selection_mode':'catalog','submitted':False}
