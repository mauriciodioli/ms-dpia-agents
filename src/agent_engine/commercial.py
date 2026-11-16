"""Authorized composite Worker. B2B owns generation/scraping, never the Planner.

Reuses PWA HMAC, TaskBox fencing and the shared single-point reservation. This
module cannot submit jobs, change permissions or deliver a user-facing result.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlsplit
from uuid import UUID
import requests
from flask import current_app, has_app_context
from sqlalchemy import select
from .errors import EngineError

TOOL = 'dpia.commercial.search'
DEPENDENCIES = frozenset({'dpia.amazon.search', 'openai.analysis'})
PATH = '/api/consultas/internal/agents-commercial'
INPUT_SCHEMA = {'type':'object','additionalProperties':False,'required':['request'],
    'properties':{'request':{'type':'object','additionalProperties':False,
        'required':['pais','ciudad','codigo_postal_id','ambito_id','categoria_id','idioma','user_message','situation'],
        'properties':{
            'pais':{'enum':['Argentina','Italia','España','Polonia','México','Uruguay']},
            'ciudad':{'type':'string','minLength':1,'maxLength':100},
            'codigo_postal_id':{'type':'integer','minimum':1},
            'ambito_id':{'type':['integer','null'],'minimum':1},
            'categoria_id':{'type':['integer','null'],'minimum':1},
            'idioma':{'enum':['es','en','it','pl']},
            'user_message':{'type':'string','minLength':1,'maxLength':4000},
            'situation':{'enum':['start','online','shop','import']}}}}}


def configured():
    return bool(has_app_context() and current_app.config.get('B2B_INTERNAL_URL')
                and current_app.config.get('PWA_ACTIVATION_SECRET'))


def service_url(config):
    base = config.get('B2B_INTERNAL_URL','').rstrip('/')
    parsed = urlsplit(base)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in ('','/') or
        not (parsed.scheme=='https' or parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1'))):
        raise EngineError('commercial_integration_unavailable',503)
    return base + PATH


class CommercialHandler:
    def __init__(self, implementations):
        self.providers = implementations

    def __call__(self, context, parameters):
        from . import models as m
        from . import point_ledger
        from .contracts import validate
        validate(INPUT_SCHEMA, parameters)
        config = self.providers.service.config
        url = service_url(config)
        secret = config.get('PWA_ACTIVATION_SECRET','')
        if not secret: raise EngineError('commercial_integration_unavailable',503)
        # Both standard integrations must pass their current checks. Credentials
        # stay in their respective services; no key is forwarded in the payload.
        scraper, _, _, _ = self.providers.prepare(context, 'dpia-scraper')
        ai, _, remaining, _ = self.providers.prepare(context, 'openai')
        budget = min(12000, remaining, ai['config']['max_output_tokens'])
        if budget < 16: raise EngineError('output_token_budget_exceeded',409)
        generation_timeout=min(ai['config']['timeout_seconds'],90)
        scraping_timeout=min(scraper['config']['timeout_seconds'],180)
        timeout=generation_timeout+scraping_timeout+45
        with context.box.engine.begin() as conn:
            job, task = context.box._owned(conn, context.lease)
            objective = job['request_snapshot'].get('objective')
            if objective and parameters['request']['user_message'].strip() != objective.strip():
                raise EngineError('commercial_request_mismatch',409)
            seconds = int((job['deadline_at'] - context.box.now()).total_seconds())
            if seconds < timeout+5: raise EngineError('provider_deadline_insufficient',409)
            reason = point_ledger.reserve(conn, job, task, context.box.now())
            if reason: raise EngineError(reason,409)
            operation = point_ledger.operation_id(task)
            agent_id = job['agent_id']
            seconds = int((job['deadline_at'] - context.box.now()).total_seconds())
        # Each provider retains its authorized timeout; preflight/catalog HTTP
        # has a separate bounded allowance within the job's remaining duration.
        body = {'owner_id':context.lease.owner_id,'agent_id':agent_id,
            'job_id':context.lease.job_id,'task_id':context.lease.task_id,
            'operation_id':operation,'request':parameters['request'],
            'max_output_tokens':budget,'model':ai['config']['model'],
            'generation_timeout_seconds':generation_timeout,'scraping_timeout_seconds':scraping_timeout}
        if context.previous_outputs:
            from .evidence_context import compact
            evidence, _ = compact(body['request']['user_message'], context.previous_outputs,max_bytes=12000)
            body['research_evidence']=json.loads(evidence)
        raw = json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(secret.encode(),stamp.encode()+b'\n'+PATH.encode()+b'\n'+raw,hashlib.sha256).hexdigest()
        context.mark_submitting(scraper['revision'])
        try:
            with requests.Session() as session:
                session.trust_env=False
                with session.request('POST',url,data=raw,headers={'Content-Type':'application/json',
                    'X-DPIA-Timestamp':stamp,'X-DPIA-Signature':signature},
                    timeout=(3.05,timeout),allow_redirects=False,stream=True) as response:
                    if response.status_code != 200:
                        raise EngineError('commercial_provider_unconfirmed',502)
                    chunks=[];length=0;started=time.monotonic()
                    for chunk in response.iter_content(16384):
                        length+=len(chunk)
                        if length>1048576 or time.monotonic()-started>timeout+5:
                            raise EngineError('commercial_provider_unconfirmed',502)
                        chunks.append(chunk)
                    data=json.loads(b''.join(chunks))
        except (requests.RequestException,ValueError):
            # Submission intent is already durable: TaskBox blocks uncertain
            # work, including lost responses; it never automatically re-POSTs.
            raise EngineError('commercial_provider_unconfirmed',502) from None
        if not isinstance(data,dict) or data.get('operation_id') != operation:
            raise EngineError('provider_invalid_response',502)
        context.mark_submitted(operation)
        usage = data.get('generation_usage')
        if not isinstance(usage,dict) or usage.get('model') != ai['config']['model'] or any(
                type(usage.get(k)) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
            raise EngineError('commercial_usage_unconfirmed',502)
        self.providers.record_usage(context,'openai.responses',usage['response_id'],
            input_tokens=usage['input_tokens'],output_tokens=usage['output_tokens'])
        if usage['output_tokens']>budget: raise EngineError('output_token_budget_exceeded',409)
        outcome = data.get('outcome',{})
        if outcome.get('status') not in ('complete','empty','partial'):
            raise EngineError('commercial_result_incomplete',502)
        from .provider_handlers import normalize_scraper
        provider_job = outcome.get('provider_job_id')
        try: UUID(provider_job)
        except (ValueError,TypeError,AttributeError): raise EngineError('provider_invalid_response',502) from None
        _, output = normalize_scraper({'success':True,'marketplace':'amazon','trabajo_id':provider_job,
            'datos':outcome.get('data'),'estado':'parcial' if outcome['status']=='partial' else 'completo'},
            secret,parameters['request']['pais'],data['retrieved_at'],10)
        self.providers.record_usage(context,'dpia.scraper',provider_job)
        # Persist raw commercial JSON and metadata in the existing task snapshot,
        # not in the public result. Manager evaluates the canonical evidence.
        from sqlalchemy import update
        with context.box.engine.begin() as conn:
            _, task = context.box._owned(conn, context.lease)
            conn.execute(update(m.tasks).where(m.tasks.c.id==task['id'],m.tasks.c.owner_id==context.lease.owner_id)
                .values(input_snapshot={**task['input_snapshot'],'commercial':{
                    'operation_id':operation,'generation_result':data.get('generation_result'),
                    'generation_usage':usage,'outcome':outcome}}))
        return output
