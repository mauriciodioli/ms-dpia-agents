"""Reviewed subset of HeyGen POST /v3/videos, Avatar IV + HeyGen Voice.
Source: https://developers.heygen.com/reference/create-video.md (2026-11-18).
No provider call or credentials belong in this validator.
"""
from jsonschema import Draft202012Validator
from .errors import EngineError

BODY_SCHEMA={'type':'object','additionalProperties':False,
 'required':['type','avatar_id','voice_id','script','title','aspect_ratio','engine','resolution','voice_settings'],
 'properties':{
  'type':{'const':'avatar'},'avatar_id':{'type':'string','minLength':1},
  'voice_id':{'type':'string','minLength':1},'script':{'type':'string','minLength':1},
  'title':{'type':'string'},'aspect_ratio':{'enum':['16:9','9:16','1:1']},
  'resolution':{'const':'720p'},'engine':{'type':'object','additionalProperties':False,
   'required':['type'],'properties':{'type':{'const':'avatar_iv'}}},
  'background':{'oneOf':[{'type':'object','additionalProperties':False,'required':['type','value'],'properties':{'type':{'const':'color'},'value':{'type':'string','pattern':'^#[0-9a-fA-F]{6}$'}}},
   {'type':'object','additionalProperties':False,'required':['type','url'],'properties':{'type':{'const':'image'},'url':{'type':'string','maxLength':2048}}}]},
  'voice_settings':{'type':'object','additionalProperties':False,'required':['engine_settings'],
   'properties':{'engine_settings':{'type':'object','additionalProperties':False,
    'required':['engine_type'],'properties':{'engine_type':{'const':'heygen_voice'},
     'model':{'const':'heygen-voice-1'}}}}}}}

def validate_video_body(body):
 if not Draft202012Validator(BODY_SCHEMA).is_valid(body):
  raise EngineError('VIDEO_PROVIDER_INVALID_REQUEST',422)
 if 'background' in body:validate_background(body['background'])
 from .provider_transport import serialize_body
 serialize_body(body)
 return body

def validate_background(value):
 from urllib.parse import urlsplit
 import re
 if value is None:return {'type':'auto'}
 if not isinstance(value,dict):raise EngineError('VIDEO_CONFIGURATION_INVALID',422)
 if value=={'type':'auto'}:return dict(value)
 if value.get('type')=='color' and set(value)=={'type','value'} and isinstance(value['value'],str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value['value']):return dict(value)
 if value.get('type')=='image' and set(value)=={'type','url'} and isinstance(value['url'],str) and len(value['url'])<=2048:
  try:parsed=urlsplit(value['url']);port=parsed.port
  except ValueError:raise EngineError('VIDEO_CONFIGURATION_INVALID',422) from None
  host=(parsed.hostname or '').lower()
  if parsed.scheme=='https' and (host=='dpia.site' or host.endswith('.dpia.site')) and not parsed.username and not parsed.password and port in (None,443):return dict(value)
 raise EngineError('VIDEO_CONFIGURATION_INVALID',422)
