"""Explicit two-stage audiovisual plan; never inherits a commercial pipeline."""
from .errors import EngineError
EXECUTION_AVAILABLE=True
SCRIPT='dpia.video.script'
PRODUCE='dpia.video.produce'
TOOLS=frozenset({SCRIPT,PRODUCE})
INPUT={'type':'object','additionalProperties':False,'required':['task_id','revision'],
       'properties':{'task_id':{'type':'integer','minimum':1},'revision':{'type':'integer','minimum':1}}}


def plan(task, agent):
    if not EXECUTION_AVAILABLE:raise EngineError('video_execution_not_available',409)
    params=task['parametros'] or {}
    if agent['limits']['max_tool_calls']<2:raise EngineError('video_execution_not_available',409)
    return {'instructions':(params.get('video') or {}).get('editor',{}).get('objective') or task['nombre'],
            'limits':agent['limits'], 'pipeline':[{'tool':tool,'parameters':{
                'task_id':task['id'],'revision':params.get('_configuration_revision',1)}} for tool in (SCRIPT,PRODUCE)]}


def is_plan(body):
    pipeline=body.get('pipeline',[])
    return isinstance(pipeline,list) and len(pipeline)==2 and all(isinstance(s,dict) for s in pipeline) and [s.get('tool') for s in pipeline]==[SCRIPT,PRODUCE]


def authorize(conn,agent,task_id,revision=None):
    from .configured_task_repository import ConfiguredTaskRepository
    rows=ConfiguredTaskRepository(conn).rows(agent,task_id)
    if not rows or rows[0]['tipo']!='VIDEO_GENERAR' or (rows[0]['parametros'] or {}).get('_deleted_at'):
        raise EngineError('VIDEO_TASK_NOT_AUTHORIZED',403)
    if revision is not None and revision!=(rows[0]['parametros'] or {}).get('_configuration_revision',1):
        raise EngineError('VIDEO_CONFIGURATION_CHANGED',409)
    return rows[0]
