"""Fixed read-only catalog requests shared by diagnostics and the video Worker."""
from .errors import EngineError

def catalog(request,path,params=None):
 rows=[];seen=set();params=dict(params or {})
 for _ in range(10):
  # request returns the full envelope: pagination is outside data.
  response=request(path,params)
  data=response.get('data')
  if isinstance(data,dict):data=data.get('items',data.get('avatars' if path.endswith('looks') else 'voices'))
  if not isinstance(data,list):raise EngineError('VIDEO_CATALOG_INVALID',502)
  rows.extend(data)
  if not response.get('has_more'):return rows
  token=response.get('next_token')
  if not isinstance(token,str) or not token or token in seen:raise EngineError('VIDEO_CATALOG_INVALID',502)
  seen.add(token);params={**params,'token':token}
 raise EngineError('VIDEO_CATALOG_PAGE_LIMIT',409)

def resources(request,language):
 from .video_worker import select_resource,voice_settings
 avatars=catalog(request,'/v3/avatars/looks')+catalog(request,'/v3/avatars/looks',{'ownership':'public'})
 voices=catalog(request,'/v3/models/audio/voices')
 public_voices=catalog(request,'/v3/models/audio/voices',{'type':'public','language':language})
 def choices(rows,key,lang=None):
  found={}
  for row in rows:
   if not isinstance(row,dict):continue
   try:identifier=select_resource([row],key,'',lang)
   except EngineError:continue
   found[identifier]={'id':identifier,'name':str(row.get('name') or identifier)[:200]}
  return list(found.values())
 available_avatars=choices(avatars,'avatar_id')
 # Public catalog is already filtered server-side; private voices still require language.
 available_voices=list({row['id']:row for row in choices(voices,'voice_id',language)+choices(public_voices,'voice_id')}.values())
 capabilities=request('/v3/videos/voice-capabilities',None).get('data')
 errors=[]
 if not available_avatars:errors.append('VIDEO_AVATAR_UNAVAILABLE')
 if not available_voices:errors.append('VIDEO_VOICE_UNAVAILABLE')
 try:settings=voice_settings(capabilities,language)
 except EngineError as error:errors.append(error.code);settings=None
 return {'avatars':available_avatars,'voices':available_voices,'language':language,
         'voice_settings':settings,'errors':errors,'ready':not errors,'submitted':False}
