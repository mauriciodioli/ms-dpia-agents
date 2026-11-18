"""REST administration endpoints; existing session/Bearer and CSRF policies."""
from flask import current_app,request
from ..api import api,endpoint,engine,arguments,identifier,json_body
from ..auth import require_session_write
from ..errors import EngineError
from .service import Service

def service():return current_app.extensions.get('rest_provider_service') or Service(engine(),current_app.config)
def write(principal):
 if principal.kind=='SESSION':require_session_write(principal,'manage-rest-providers')
def body():
 if request.content_length and request.content_length>65536:raise EngineError('invalid_contract')
 return json_body()

@api.route('/rest/providers',methods=['GET','POST'])
@endpoint()
def rest_providers(conn,principal,repo):
 arguments()
 if request.method=='GET':return service().listing(principal)
 write(principal);return {'provider':service().save(principal,body())},201

@api.route('/rest/providers/<provider_id>',methods=['GET','PATCH'])
@endpoint()
def rest_provider(conn,principal,repo,provider_id):
 arguments();identifier(provider_id)
 if request.method=='GET':return {'provider':service().detail(principal,provider_id)}
 write(principal);return {'provider':service().save(principal,body(),provider_id)}

@api.put('/rest/providers/<provider_id>/credential')
@endpoint()
def rest_credential(conn,principal,repo,provider_id):
 arguments();identifier(provider_id);write(principal)
 return {'provider':service().credential(principal,provider_id,body())}

@api.patch('/rest/providers/<provider_id>/status')
@endpoint()
def rest_status(conn,principal,repo,provider_id):
 arguments();identifier(provider_id);write(principal)
 return {'provider':service().mutate(principal,provider_id,body())}

@api.post('/rest/providers/<provider_id>/disconnect')
@endpoint()
def rest_disconnect(conn,principal,repo,provider_id):
 arguments();identifier(provider_id);write(principal)
 return {'provider':service().mutate(principal,provider_id,body(),disconnect=True)}

@api.post('/rest/providers/<provider_id>/test')
@endpoint()
def rest_probe(conn,principal,repo,provider_id):
 arguments();identifier(provider_id);write(principal);command=body()
 if not isinstance(command,dict) or set(command)!={'expected_revision'} or type(command['expected_revision']) is not int:raise EngineError('invalid_contract')
 return service().read(principal,provider_id,probe=True,revision=command['expected_revision'])

@api.get('/rest/providers/<provider_id>/operations')
@endpoint()
def rest_operations(conn,principal,repo,provider_id):
 arguments();return service().operations(principal,identifier(provider_id))

@api.post('/rest/providers/<provider_id>/read/<operation>')
@endpoint()
def rest_read_operation(conn,principal,repo,provider_id,operation):
 arguments();identifier(provider_id);write(principal)
 if body()!={}:raise EngineError('invalid_contract')
 return service().read(principal,provider_id,operation)

@api.post('/rest/providers/<provider_id>/prepare-video')
@endpoint()
def rest_prepare(conn,principal,repo,provider_id):
 arguments();write(principal);return service().prepare(principal,identifier(provider_id),body())

@api.post('/rest/providers/<provider_id>/video-resources')
@endpoint()
def rest_video_resources(conn,principal,repo,provider_id):
 arguments();write(principal);command=body()
 if not isinstance(command,dict) or set(command)!={'language'}:raise EngineError('invalid_contract',422)
 return service().video_resources(principal,identifier(provider_id),command['language'])
