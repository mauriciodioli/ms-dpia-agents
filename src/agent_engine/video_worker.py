"""Audiovisual handlers on the existing fenced Worker runtime; no delivery here."""
import json
import re
import time
from decimal import Decimal
from urllib.parse import urlsplit
from sqlalchemy import select,update,insert
from . import models as m
from .errors import EngineError
from .video_plan import SCRIPT,PRODUCE,TOOLS
from .video_sources import source_context
from .video_script import build,OpenAIScript
from .contracts import RESULT,validate
from .worker import Handler,HandlerRegistry


def encoded_result(script, video=None):
    output={'schema_version':'agents.result.v1','summary':script['description'],
            'findings':[],'sources':[],'warnings':[]}
    if not video:output['video_script']=script
    if video:
        output['video']=video
        output['items']=[{'title':script['title'],'description':script['description'],'url':video['url']}]
    validate(RESULT,output)
    return output


def prior_script(outputs):
    for output in outputs:
        if isinstance(output.get('video_script'),dict):return output['video_script']
        for finding in output.get('findings',[]):
            try:value=json.loads(finding['text'])
            except (ValueError,KeyError,TypeError):continue
            if 'video_script' in value:return value['video_script']
    raise EngineError('VIDEO_SCRIPT_NOT_PERSISTED',409)


class VideoHandlers:
    def __init__(self,engine,config,providers=None,rest=None,sleep=time.sleep):
        from .provider_handlers import ProviderHandlers
        from .integrations import IntegrationService
        from .rest_providers.service import Service
        self.engine,self.config=engine,config
        self.providers=providers or ProviderHandlers(IntegrationService(engine,config))
        self.rest=rest or Service(engine,config)
        self.sleep=sleep

    def context(self,context,parameters):
        with self.engine.begin() as conn:
            job,task=context.box._owned(conn,context.lease)
            context.box.authorized(conn,job,task,require_provider=False)
            if job['legacy_task_id']!=parameters['task_id']:raise EngineError('VIDEO_TASK_NOT_AUTHORIZED',403)
            source=source_context(conn,job)
            if source['configuration_revision']!=parameters['revision']:raise EngineError('VIDEO_CONFIGURATION_CHANGED',409)
            return dict(job),dict(task),source

    def script(self,context,parameters):
        job,task,source=self.context(context,parameters)
        custom=bool(source['video']['script'].get('custom_script','').strip())
        from .video_operations import require
        with self.engine.begin() as conn:require(conn,'custom_script' if custom else 'openai_script')
        if custom:return encoded_result(build(source,None))
        row,secret,remaining,_=self.providers.prepare(context,'openai')
        if min(row['config']['max_output_tokens'],remaining)<16:raise EngineError('output_token_budget_exceeded',409)
        ai=OpenAIScript(self.providers.service.http,row['config']['model'],secret,
                       row['config']['timeout_seconds'],min(row['config']['max_output_tokens'],remaining))
        def generate(request,schema):
            # Local JSON validation is complete before recording submission intent.
            from .provider_transport import serialize_body
            raw=serialize_body(request)
            bound=self.config.get('OPENAI_ANALYSIS_MAX_INPUT_TOKENS',32000)
            if type(bound) is not int or len(raw)>min(24000,bound-2048):raise EngineError('VIDEO_SCRIPT_SOURCE_LIMIT',422)
            with self.engine.begin() as conn:require(conn,'openai_script')
            context.mark_submitting(row['revision'])
            try:
                return ai(request,schema)
            finally:
                if isinstance(ai.reference,str) and ai.reference:
                    context.mark_submitted(ai.reference)
                    usage=ai.usage
                    if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
                        self.providers.record_usage(context,'openai.responses',ai.reference)
                        raise EngineError('invalid_token_usage',502)
                    self.providers.record_usage(context,'openai.responses',ai.reference,
                        input_tokens=usage['input_tokens'],output_tokens=usage['output_tokens'])
        return encoded_result(build(source,generate))

    def provider(self,conn,owner):
        from .shared_video_provider import resolve
        row=resolve(conn,owner)
        if not row['credential_ciphertext'] or row['credential_origin']!=row['base_url'] or row['health']!='HEALTHY':
            raise EngineError('rest_provider_not_ready',409)
        return row

    def request(self,row,secret,path,params=None,full=False):
        status,data=self.rest.http.get(row['base_url'],path,secret,'X-Api-Key',row['timeout_seconds'],**({'params':params} if params is not None else {}))
        if status!=200:raise EngineError({404:'VIDEO_RESOURCE_NOT_FOUND',401:'rest_unauthorized',403:'rest_forbidden',429:'rest_rate_limited'}.get(status,'rest_upstream_error'),502)
        if secret and secret in json.dumps(data,ensure_ascii=False):raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
        return data if full else data.get('data')

    def checkpoint(self,context,value):
        from .provider_transport import serialize_body
        serialize_body(value)
        with self.engine.begin() as conn:
            _,task=context.box._owned(conn,context.lease)
            conn.execute(update(m.tasks).where(m.tasks.c.id==task['id'],m.tasks.c.owner_id==context.lease.owner_id).values(output=value))

    def produce(self,context,parameters):
        job,task,source=self.context(context,parameters)
        script=prior_script(context.previous_outputs)
        production=dict(source['video']['production'])
        if not production['automatic_production'] and job.get('schedule_id'):
            # A one-off scheduled from the user's task is an explicit request to
            # produce once; retain the separate approval for recurring schedules.
            with self.engine.connect() as conn:
                schedule=conn.execute(select(m.schedules).where(m.schedules.c.id==job['schedule_id'],
                    m.schedules.c.owner_id==job['owner_id'],m.schedules.c.agent_id==job['agent_id'],
                    m.schedules.c.legacy_task_id==job['legacy_task_id'])).mappings().first()
            definition=(schedule['definition'] or {}) if schedule else {}
            author=definition.get('author') or {}
            if (definition.get('configured_task_schedule') is True and definition.get('frequency')=='ONCE'
                    and author.get('kind') in ('SESSION','PWA_SERVICE')):
                production['automatic_production']=True
        from .video_operations import require
        with self.engine.begin() as conn:require(conn,'heygen_produce')
        if production.get('format') not in ('16:9','9:16','1:1'):raise EngineError('VIDEO_CONFIGURATION_INVALID',422)
        if production.get('provider')!='heygen':raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
        with self.engine.begin() as conn:row=self.provider(conn,job['owner_id'])
        try:secret=json.loads(self.rest.secrets.decrypt(row))
        except (ValueError,TypeError):raise EngineError('integration_encryption_unavailable',503) from None
        if not isinstance(secret,str):raise EngineError('integration_encryption_unavailable',503)
        checkpoint=task.get('output') or {}
        remote=task.get('provider_job_id')
        if remote:
            if checkpoint.get('provider_id')!=row['id']:raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
            account=self.request(row,secret,'/v3/users/me')
            if not isinstance(account,dict) or account.get('username')!=checkpoint.get('estimate',{}).get('account_id'):
                raise EngineError('VIDEO_PROVIDER_SELECTION_REQUIRED',409)
        if not remote:
            if task['provider_submission_state']!='NOT_SUBMITTED':raise EngineError('VIDEO_SUBMISSION_UNCERTAIN',409)
            if not production['automatic_production']:raise EngineError('VIDEO_PRODUCTION_APPROVAL_REQUIRED',409)
            if production['budget_credits']<=0:raise EngineError('VIDEO_BUDGET_INSUFFICIENT',409)
            from .heygen_resources import resolve_resource
            read=lambda path,params=None:self.request(row,secret,path,params,full=True)
            avatar,avatar_row=resolve_resource(read,'avatar_id',production['avatar_id'],production['language'])
            voice,voice_row=resolve_resource(read,'voice_id',production['voice_id'],production['language'])
            body={'type':'avatar','avatar_id':avatar,'voice_id':voice,
                  'script':'\n'.join(s['narration'] for s in script['scenes']),
                  'title':script['title'],'aspect_ratio':production['format'],'engine':{'type':'avatar_iv'},'resolution':'720p'}
            from .heygen_video_contract import validate_background
            background=validate_background(production.get('background',{'type':'auto'}))
            if background['type']!='auto':body['background']=background
            capabilities=self.request(row,secret,'/v3/videos/voice-capabilities')
            body['voice_settings']=voice_settings(capabilities,production['language'])
            if voice_row.get('mode')=='professional':
                body['voice_settings']['engine_settings'].pop('model',None)
            from .provider_transport import serialize_body
            from .heygen_video_contract import validate_video_body
            validate_video_body(body)
            account=self.request(row,secret,'/v3/users/me')
            from .video_estimates import estimate
            from .video_cost_api import load
            from .video_costs import reserve,transition
            with self.engine.begin() as conn:
                current_job,current_task=context.box._owned(conn,context.lease)
                current=self.provider(conn,job['owner_id'])
                if current['revision']!=row['revision']:raise EngineError('VIDEO_CONFIGURATION_CHANGED',409)
                quote=estimate(conn,row,body,production['duration_seconds'],context.box.now(),account,job_id=current_job['id'],
                    avatar_type=avatar_row.get('avatar_type'),voice_mode=voice_row.get('mode'))
                rate=load(conn)['usd_per_credit']
                reservation=reserve(conn,current_job,current_task,quote['estimated_usd'],
                    {'AGENTS_VIDEO_USD_PER_CREDIT':rate},production,quote['reference'],context.box.now())
                reservation['provisional_estimate']=quote.get('provisional',False)
                checkpoint={'video_script':script,'reservation':reservation,'estimate':quote,'provider_id':row['id'],
                            'provider_revision':row['revision'],'request':body,'state':'PREPARED'}
                conn.execute(update(m.tasks).where(m.tasks.c.id==task['id'],m.tasks.c.owner_id==job['owner_id']).values(output=checkpoint))
            # Recheck task preferences immediately before the billable boundary.
            self.context(context,parameters)
            def before_send():
                from datetime import datetime
                if datetime.strptime(quote['valid_until'],'%Y-%m-%dT%H:%M:%SZ')<=context.box.now():raise EngineError('VIDEO_COST_NOT_VERIFIABLE',409)
                self.context(context,parameters)
                with self.engine.begin() as conn:
                    require(conn,'heygen_produce')
                    current=self.provider(conn,job['owner_id'])
                    if current['revision']!=row['revision']:raise EngineError('VIDEO_CONFIGURATION_CHANGED',409)
                context.mark_submitting()
                with self.engine.begin() as conn:transition(conn,job['owner_id'],reservation,'dispatching',context.box.now())
            from .errors import ProviderNotSent
            try:
                status,data=self.rest.http.post_video(row['base_url'],secret,row['timeout_seconds'],body,task['id'],before_send=before_send)
            except ProviderNotSent:
                # Only the trusted transport can prove conn.request was not called.
                with self.engine.begin() as conn:
                    _,current=context.box._owned(conn,context.lease)
                    if current['provider_job_id'] is not None:raise EngineError('VIDEO_SUBMISSION_UNCERTAIN',409)
                    conn.execute(update(m.tasks).where(m.tasks.c.id==task['id'],m.tasks.c.owner_id==job['owner_id']).values(provider_submission_state='NOT_SUBMITTED'))
                    transition(conn,job['owner_id'],reservation,'released',context.box.now())
                raise
            if status!=200:raise EngineError('VIDEO_PROVIDER_GENERATION_FAILED',502)
            remote=(data.get('data') or {}).get('video_id')
            if not isinstance(remote,str) or secret in remote or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',remote):raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
            context.mark_submitted(remote)
            checkpoint={**checkpoint,'remote_id':remote,'state':'SUBMITTED'}
            self.checkpoint(context,checkpoint)
        if not isinstance(remote,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',remote):raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
        with self.engine.begin() as conn:
            context.box._owned(conn,context.lease)
            used=conn.execute(select(m.usage).where(m.usage.c.owner_id==job['owner_id'],
                m.usage.c.provider_id=='heygen.rest',m.usage.c.provider_record_id==remote).with_for_update()).mappings().first()
            if used and used['job_id']!=job['id']:raise EngineError('VIDEO_PROVIDER_REFERENCE_CONFLICT',409)
            if not used:
                from uuid import uuid4
                conn.execute(insert(m.usage).values(id=str(uuid4()),owner_id=job['owner_id'],job_id=job['id'],
                    provider_id='heygen.rest',provider_record_id=remote,verified=True,evidence_source='PROVIDER_RESPONSE',
                    calls=1,created_at=context.box.now()))
        while True:
            context.heartbeat()
            result=self.request(row,secret,'/v3/videos/'+remote)
            if not isinstance(result,dict) or result.get('id')!=remote:raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
            state=result.get('status')
            if state in ('failed','error'):raise EngineError('VIDEO_PROVIDER_GENERATION_FAILED',502)
            if state=='completed':
                url=result.get('video_url')
                parsed=urlsplit(url) if isinstance(url,str) else None
                if not parsed or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                    raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
                # Provider does not expose an attributable charge in this contract.
                # Keep holds pending; never label duration*rate as a confirmed charge.
                from .video_costs import transition
                with self.engine.begin() as conn:
                    context.box._owned(conn,context.lease)
                    transition(conn,job['owner_id'],checkpoint['reservation'],'pending',context.box.now())
                video={'url':url,'provider':'heygen','remote_id':remote,'state':'COMPLETED',
                       'script':script,'cost':{**checkpoint['reservation'],'actual_usd':None,'reconciliation':'PENDING'}}
                return encoded_result(script,video)
            if state not in ('waiting','pending','processing'):raise EngineError('VIDEO_PROVIDER_INVALID_RESPONSE',502)
            self.sleep(2)


def select_resource(data,key,selected,language=None):
    if isinstance(data,dict):data=data.get('avatars' if key=='avatar_id' else 'voices',data.get('items'))
    if not isinstance(data,list):raise EngineError('VIDEO_CATALOG_INVALID',502)
    if key=='avatar_id':
        data=[{**r,'avatar_id':r.get('id'),'status':'ACTIVE'} for r in data if isinstance(r,dict)
              and r.get('status','completed')=='completed' and 'avatar_iv' in r.get('supported_api_engines',[])]
    candidates=[r for r in data if isinstance(r,dict) and isinstance(r.get(key),str)
                and r.get('status','ACTIVE')=='ACTIVE' and (not language or r.get('language')==language)]
    if selected:
        candidates=[r for r in candidates if r[key]==selected]
    if not candidates:raise EngineError('VIDEO_AVATAR_UNAVAILABLE' if key=='avatar_id' else 'VIDEO_VOICE_UNAVAILABLE',409)
    return sorted(candidates,key=lambda r:r[key])[0][key]


def video_handlers(engine,config,**kwargs):
    implementations=VideoHandlers(engine,config,**kwargs)
    registry=HandlerRegistry()
    registry.register(SCRIPT,Handler(implementations.script,RESULT,requires_provider_grant=False))
    registry.register(PRODUCE,Handler(implementations.produce,RESULT,requires_provider_grant=False))
    return registry


def voice_settings(data,language):
    if not isinstance(data,dict) or not isinstance(data.get('capabilities'),list):raise EngineError('VIDEO_CATALOG_INVALID',502)
    for row in data['capabilities']:
        if row.get('language')!=language or row.get('locale') is not None:continue
        for engine in row.get('engines',[]):
            if engine.get('engine')=='heygen_voice':
                models=engine.get('models',[])
                settings={'engine_type':'heygen_voice'}
                if models:
                    if 'heygen-voice-1' not in models:continue
                    settings['model']='heygen-voice-1'
                return {'engine_settings':settings}
    raise EngineError('VIDEO_VOICE_LANGUAGE_UNSUPPORTED',409)
