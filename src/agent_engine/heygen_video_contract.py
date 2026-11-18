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
  'voice_settings':{'type':'object','additionalProperties':False,'required':['engine_settings'],
   'properties':{'engine_settings':{'type':'object','additionalProperties':False,
    'required':['engine_type'],'properties':{'engine_type':{'const':'heygen_voice'},
     'model':{'const':'heygen-voice-1'}}}}}}}

def validate_video_body(body):
 if not Draft202012Validator(BODY_SCHEMA).is_valid(body):
  raise EngineError('VIDEO_PROVIDER_INVALID_REQUEST',422)
 from .provider_transport import serialize_body
 serialize_body(body)
 return body
