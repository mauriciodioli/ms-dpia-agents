"""Reviewed Novedades context → validated OpenAI plan → existing DPIA transport."""
import json
from services.query_preparation import PreparationError, result_template
from services.query_sources import EXTERNAL
from services.result_generation import validate_result, sheet_rows
from services.query_execution import execute_sources


def validate_configuration(config):
    def not_started(message):
        error=PreparationError(message,503);error.not_started=True;return error
    # Check configuration before reserving or contacting either provider.
    if not config.get('LIVE_PROVIDER_CALLS_ENABLED',False):
        raise not_started('Las llamadas reales están deshabilitadas.')
    if not config.get('OPENAI_API_KEY'):
        raise not_started('La generación de novedades no está configurada.')
    if not config.get('SCRAPEADOR_SERVICE_KEY'):
        raise not_started('Falta SCRAPEADOR_SERVICE_KEY.')


def run_novelties(prepared, config, quota, operation_id, generate_fn):
    external=[source for source in prepared['sources'] if source in EXTERNAL]
    if len(external)!=1:
        raise PreparationError('Elegí un marketplace para buscar novedades.')
    validate_configuration(config)
    user_id=prepared['context']['usuario']
    quota.reserve_direct(operation_id,user_id,prepared)
    execution=quota.operation(operation_id,user_id)
    # Use the original snapshot on replay, including its date.
    prepared=execution['prepared']
    outcome=json.loads(execution['outcome']) if execution.get('outcome') else {}
    generated=outcome.get('generation_result')
    if execution['state']!='reserved':
        if not generated:
            return {'success':True,'request_id':operation_id,'flow':'novedades',
                'result':result_template(prepared),'rows':[],'sources':{external[0]:outcome or {'status':'pending','products':[]}}}
        return {'success':True,'request_id':operation_id,'flow':'novedades',
            'result':generated,'rows':sheet_rows(generated),'sources':{external[0]:outcome}}
    if generated is None:
        try:claim=quota.novel_generation(operation_id,user_id)
        except PreparationError as exc:
            if exc.status!=409:raise
            current=quota.operation(operation_id,user_id)
            saved=json.loads(current['outcome']) if current.get('outcome') else {'status':'pending','products':[]}
            result=saved.get('generation_result') or result_template(prepared)
            return {'success':True,'request_id':operation_id,'flow':'novedades','result':result,
                    'rows':sheet_rows(result),'sources':{external[0]:saved}}
        generated=claim.get('result')
        if generated is None:
            token=claim['token']
            try:
                generated=validate_result(generate_fn(prepared,config),prepared)
                if not generated['needs_clarification']:
                    for plan in generated['scrape_plan']:
                        query=plan['search_query'].strip()
                        if not query or len(query)>500:
                            raise PreparationError('OpenAI no devolvió una búsqueda válida para el scraper.',502)
                        plan['search_query']=query
            except PreparationError as exc:
                quota.novel_generation(operation_id,user_id,token=token,error=str(exc))
                exc.not_started=True
                raise
            quota.novel_generation(operation_id,user_id,token=token,result=generated)
    if generated['needs_clarification']:
        outcomes={source:{'status':'clarification_required','products':[]} for source in prepared['sources']}
    else:
        outcomes=execute_sources(prepared,generated,config,quota=quota,operation_id=operation_id)
    return {'success':True,'result':generated,'rows':sheet_rows(generated),'sources':outcomes,
            'request_id':operation_id,'flow':'novedades','context_ids':prepared['ids']}
