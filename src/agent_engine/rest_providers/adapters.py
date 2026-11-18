"""Versioned, explicit operation catalogs. No endpoint autodiscovery/execution plug-ins."""
from ..errors import EngineError

class HeyGen:
 id='heygen';name='HeyGen Video AI';base_url='https://api.heygen.com';header='X-Api-Key'
 operations={
  'account':dict(label='Cuenta',method='GET',path='/v3/users/me',available=True,documentation='https://developers.heygen.com/reference/get-current-user.md'),
  'quota':dict(label='Saldo y cuota de la cuenta',method='GET',path='/v3/users/me',available=True,documentation='https://developers.heygen.com/reference/get-current-user.md'),
  'avatars':dict(label='Avatares',method='GET',path='/v3/avatars',available=True,documentation='https://developers.heygen.com/reference/list-avatar-groups.md'),
  'voices':dict(label='Voces',method='GET',path='/v3/models/audio/voices',available=True,documentation='https://developers.heygen.com/docs/voices/overview.md'),
  'generate_video':dict(label='Generar vídeo (solo preparación, envío deshabilitado)',method='POST',path='/v3/videos',available=False,documentation='https://developers.heygen.com/reference/create-video.md'),
  'video_status':dict(label='Seguimiento de vídeo (reservado para próxima etapa)',method='GET',path='/v3/videos/{video_id}',available=False,documentation='https://developers.heygen.com/reference/get-video.md')}
 @classmethod
 def prepare(cls,body):
  if not isinstance(body,dict) or set(body)-{'type','avatar_id','script','voice_id','title'} or body.get('type')!='avatar':raise EngineError('rest_invalid_video_draft',422)
  for key,limit in [('avatar_id',255),('voice_id',255),('script',20000)]:
   if not isinstance(body.get(key),str) or not 1<=len(body[key].strip())<=limit:raise EngineError('rest_invalid_video_draft',422)
  if 'title' in body and (not isinstance(body['title'],str) or len(body['title'])>500):raise EngineError('rest_invalid_video_draft',422)
  return {'prepared':True,'submitted':False,'operation':'generate_video','method':'POST','path':'/v3/videos','body':body}

ADAPTERS={'heygen':HeyGen}
def adapter(identifier):
 if not isinstance(identifier,str) or identifier not in ADAPTERS:raise EngineError('rest_adapter_not_supported',422)
 return ADAPTERS[identifier]
