"""OpenAI JSON generation. No scraping, publishing, payments or Sheets writes."""
import json
import logging
import re
import requests
from jsonschema import Draft202012Validator, ValidationError
from services.query_preparation import result_template, build_private_prompt, PreparationError
from services.query_media import model_input


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


TEXT={'type':'string'}
PRICE={'anyOf':[{'type':'number','minimum':0},{'type':'string','enum':['N/D']}]}


def result_schema(prepared):
    base=result_template(prepared)
    def infer(value):
        if isinstance(value,dict):return obj({k:infer(v) for k,v in value.items()})
        if isinstance(value,bool):return {'type':'boolean'}
        if isinstance(value,int):return {'type':'integer'}
        if isinstance(value,list):return {'type':'array','items':TEXT}
        return TEXT
    schema=infer(base)
    props=schema['properties']
    props['type']={'type':'string','enum':['results']}
    props['version']={'type':'string','enum':['dpia.results.v2']}
    props['query']['properties']['raw_user_message']={'type':'string'}
    props['context']=obj({key:{'type':'integer' if isinstance(value,int) else 'string','enum':[value]}
                          for key,value in prepared['context'].items()})
    props['constraints']['properties']['price']=obj({'min':PRICE,'max':PRICE,'currency':{'type':'string','enum':[base['constraints']['price']['currency']]}})
    props['constraints']['properties']['delivery_max_days']={'anyOf':[{'type':'integer','minimum':0},{'type':'string','enum':['N/D']}]}
    props['scrape_plan']={'type':'array','items':obj({'source':{'type':'string','enum':[s for s in prepared.get('sources',['amazon','ebay','aliexpress']) if s in ('amazon','ebay','aliexpress','mercadolibre')] or ['amazon','ebay','aliexpress']},
        'country_domain':TEXT,'search_query':TEXT,'search_url':TEXT,'max_results':{'type':'integer','minimum':1,'maximum':20}})}
    fields={key:TEXT for key in ('producto','categoria','pais','fuente','motivo_tendencia','descripcion','fecha',
        'motivo_tendencia_extendido','ambito','codigoPostal','idioma','afiliado_link')}
    fields.update({'precios':obj({key:PRICE for key in ('amazon','ebay','aliexpress')}),
        'precio_venta_sugerido':PRICE,'margen_estimado':{'anyOf':[{'type':'number'},{'type':'string','enum':['N/D']}]},
        'busquedas':obj({key:TEXT for key in ('amazon','ebay','aliexpress')}),'usuario':{'type':'integer'},
        'estado':{'type':'string','enum':['CANDIDATO']},'botonCompra':{'type':'boolean','enum':[False]},
        'pagoOnline':{'type':'boolean','enum':[False]},'validado':{'type':'boolean','enum':[False]},
        'score_hint':{'type':'number','minimum':0,'maximum':100}})
    fields.update({key:TEXT for key in ('imagen','imagen2','imagen3','imagen4','imagen5','imagen6')})
    # Allow an empty clarification response, otherwise require the requested batch.
    props['items']={'anyOf':[{'type':'array','items':obj(fields),'minItems':0,'maxItems':0},
                            {'type':'array','items':obj(fields),'minItems':5,'maxItems':10}]}
    if prepared['mode']=='explorar':
        props['needs_clarification']={'type':'boolean','enum':[False]}
        props['clarifying_question']={'type':'string','enum':['']}
        props['items']={'type':'array','items':obj(fields),'minItems':5,'maxItems':10}
        props['scrape_plan']['maxItems']=0
    return schema


def validate_result(result, prepared):
    try:Draft202012Validator(result_schema(prepared)).validate(result)
    except ValidationError:raise PreparationError('La respuesta generada no cumple el formato DPIA.',502) from None
    if (result['context']!=prepared['context'] or
            result['query']['raw_user_message']!=prepared['user_message']):
        raise PreparationError('La respuesta no corresponde a tu consulta.',502)
    if result['needs_clarification']:
        if result['items'] or not result['clarifying_question'].strip():
            raise PreparationError('La aclaración recibida no es válida.',502)
    else:
        count=len(result['items'])
        if not 5<=count<=10:
            logging.getLogger(__name__).warning('DPIA response validation: reason=candidate_count count=%d needs_clarification=false question_present=%s',count,bool(result['clarifying_question']))
            raise PreparationError(f'La IA devolvió {count} candidatos sin solicitar aclaración; se requieren entre 5 y 10. No se inició el scraping.',502)
        if result['clarifying_question']:
            logging.getLogger(__name__).warning('DPIA response validation: reason=unexpected_clarification count=%d needs_clarification=false question_present=true',count)
            raise PreparationError('La IA devolvió candidatos y una pregunta de aclaración incompatible. No se inició el scraping.',502)
    allowed={s for s in prepared.get('sources',['amazon','ebay','aliexpress']) if s in ('amazon','ebay','aliexpress','mercadolibre')}
    plans=[row['source'] for row in result['scrape_plan']]
    if len(set(plans))!=len(plans) or set(plans)!=allowed:
        raise PreparationError('El plan no coincide con los orígenes elegidos.',502)
    seen=set()
    for item in result['items']:
        key=item['producto'].strip().casefold()
        if not key or key in seen:raise PreparationError('La respuesta contiene candidatos repetidos o vacíos.',502)
        seen.add(key)
        for field in ('ambito','categoria','pais','codigoPostal','usuario','fecha','idioma'):
            if prepared['mode']=='explorar':
                # Card metadata belongs to DPIA's verified request/session context.
                item[field]=prepared['context'][field]
            elif item[field]!=prepared['context'][field]:
                raise PreparationError('El contexto del candidato no coincide.',502)
        if item['afiliado_link']:raise PreparationError('Los candidatos no pueden incluir afiliación sin verificar.',502)
    expected=result_template(prepared)['constraints']
    if (result['constraints']['shipping_to']!=expected['shipping_to'] or
            result['constraints']['price']['currency']!=expected['price']['currency']):
        raise PreparationError('El país o la moneda generados no coinciden.',502)
    # This text-only step has no verified marketplace evidence. Never display
    # model guesses as observed prices, margins, sources or product galleries.
    for item in result['items']:
        item['precios']={source:'N/D' for source in ('amazon','ebay','aliexpress')}
        if prepared['mode']!='explorar':item['precio_venta_sugerido']='N/D'
        item['margen_estimado']='N/D'
        item['fuente']='N/D'
        for key in ('imagen','imagen2','imagen3','imagen4','imagen5','imagen6'):item[key]='N/D'
    return result


def diagnostic_message(message):
    """Return technical summaries only; never log free-form provider text.

    Error messages can echo inputs, personal data or credentials. A denylist
    cannot reliably remove those, so unrecognized messages are omitted.
    """
    if not isinstance(message,str) or not message:
        return '[message unavailable]'
    text=message[:8000].casefold()
    summaries=(
        ('invalid schema', 'Invalid JSON schema'),
        ('incorrect api key', 'Incorrect API key provided [value omitted]'),
        ('invalid api key', 'Invalid API key [value omitted]'),
        ('insufficient_quota', 'API quota unavailable'),
        ('exceeded your current quota', 'API quota unavailable'),
        ('rate limit', 'API rate limit exceeded'),
        ('does not exist or you do not have access', 'Model unavailable or access denied'),
        ('unsupported parameter', 'Unsupported API parameter'),
        ('unknown parameter', 'Unknown API parameter'),
        ('invalid value', 'Invalid API parameter value'),
        ('server had an error', 'Provider internal error'),
    )
    for marker,summary in summaries:
        if marker in text:
            if marker=='invalid schema':
                # Only fixed schema keywords and fixed reasons can reach logs.
                keywords=[name for name in ('additionalProperties','required','anyOf',
                    'minItems','maxItems','minimum','maximum','enum','type')
                    if re.search(r'(?<![a-z])'+name.casefold()+r'(?![a-z])',text)]
                reasons=[reason for marker,reason in (
                    ('not permitted','not permitted'),('not supported','not supported'),
                    ('required to be supplied','missing required keyword'),
                    ('must be','invalid keyword value')) if marker in text]
                summary+='; keywords='+(','.join(keywords) or 'unknown')
                summary+='; reason='+(','.join(reasons) or 'unspecified')
            return summary
    return '[message omitted: unrecognized provider text]'


def provider_error(response, secrets=()):
    """Classify rejections without exposing provider text, prompts or credentials."""
    code='unknown';error_type='unknown';message=None
    try:
        payload=response.json()
        error=payload.get('error') if isinstance(payload,dict) else None
        if isinstance(error,dict):
            message=error.get('message')
            if error.get('type') in ('invalid_request_error','authentication_error',
                    'permission_error','rate_limit_error','insufficient_quota',
                    'server_error','api_error','requests','tokens'):
                error_type=error['type']
        candidate=error.get('code') if isinstance(error,dict) else None
        if candidate in ('invalid_api_key','insufficient_quota','rate_limit_exceeded',
                         'model_not_found','invalid_json_schema','unsupported_parameter',
                         'invalid_value','billing_hard_limit_reached'):
            code=candidate
    except (ValueError,TypeError,AttributeError):
        pass
    request_id=response.headers.get('x-request-id','')
    if not isinstance(request_id,str) or not re.fullmatch(r'(?:req_[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})',request_id) or any(secret and secret in request_id for secret in secrets):request_id='unavailable'
    logging.getLogger(__name__).warning(
        'OpenAI rejection: status=%s type=%s code=%s request_id=%s message=%s',
        response.status_code,error_type,code,request_id,diagnostic_message(message))
    if code in ('insufficient_quota','billing_hard_limit_reached'):
        message='La cuenta de OpenAI no tiene cuota disponible. Revisá el saldo y el límite de gasto del proyecto.'
    elif response.status_code==401 or code=='invalid_api_key':
        message='OpenAI rechazó la credencial del servidor. Revisá OPENAI_API_KEY en el entorno desplegado.'
    elif response.status_code==403:
        message='El proyecto de OpenAI no tiene permiso para realizar esta consulta.'
    elif response.status_code==404 or code=='model_not_found':
        message='El modelo configurado no está disponible para este proyecto de OpenAI. Revisá OPENAI_MODEL.'
    elif response.status_code==429:
        message='OpenAI alcanzó el límite temporal de solicitudes. Esperá un momento y reintentá.'
    elif code=='invalid_json_schema':
        message='OpenAI rechazó el formato de respuesta configurado. Es necesario revisar el esquema en el servidor.'
    elif response.status_code==400:
        message='OpenAI rechazó los parámetros de la consulta. Revisá la configuración del modelo en el servidor.'
    elif response.status_code>=500:
        message='OpenAI no está disponible temporalmente. Reintentá más tarde.'
    else:
        message='OpenAI rechazó la consulta. Revisá el registro del servidor para identificar la causa.'
    return PreparationError(message,502)


def generate(prepared, config):
    key=config.get('OPENAI_API_KEY','')
    if not key:raise PreparationError('La generación de consultas no está configurada todavía.',503)
    schema=result_schema(prepared)
    prompt=build_private_prompt(prepared)+'\nIncluí imagen, imagen2, imagen3, imagen4, imagen5 e imagen6 como "N/D" si no están verificadas.'
    try:
        with requests.post('https://api.openai.com/v1/responses',headers={'Authorization':f'Bearer {key}'},
                json={'model':config.get('OPENAI_MODEL','gpt-4o-mini'),'store':False,'instructions':prompt,
                      'input':model_input(prepared),'max_output_tokens':12000,
                      'text':{'format':{'type':'json_schema','name':'dpia_results_v2','strict':True,'schema':schema}}},
                timeout=(3.05,90),allow_redirects=False) as response:
            if response.status_code!=200:
                provider_error(response,secrets=(key,config.get('SCRAPEADOR_SERVICE_KEY','')))
                # Diagnostics must not change the public error contract.
                raise PreparationError('No se pudo generar la consulta. Reintentá más tarde.',502)
            payload=response.json()
        if payload.get('status')!='completed':raise PreparationError('La generación no se completó.',502)
        outputs=[part['text'] for output in payload.get('output',[]) if output.get('type')=='message'
                 for part in output.get('content',[]) if part.get('type')=='output_text']
        if len(outputs)!=1:raise PreparationError('No se recibió un resultado JSON completo.',502)
        def invalid_constant(value):
            raise ValueError('Non-JSON numeric value')
        result=json.loads(outputs[0],parse_constant=invalid_constant)
        serialized=json.dumps(result,allow_nan=False)
        for secret in (key,config.get('SCRAPEADOR_SERVICE_KEY','')):
            if secret and secret in serialized:raise PreparationError('La respuesta generada no es válida.',502)
        return validate_result(result,prepared)
    except requests.Timeout:raise PreparationError('La generación tardó demasiado. Reintentá.',504) from None
    except (requests.RequestException,ValueError,TypeError,KeyError,AttributeError):
        raise PreparationError('No se recibió una respuesta válida del generador.',502) from None


def sheet_rows(result):
    """Compatibility mapping only; does not write to Google Sheets."""
    rows=[]
    for item in result['items']:
        row={key:item[key] for key in ('descripcion','precio_venta_sugerido','margen_estimado','fecha',
             'motivo_tendencia_extendido','ambito','codigoPostal','usuario','estado','botonCompra','idioma',
             'pagoOnline','validado','afiliado_link','imagen','imagen2','imagen3','imagen4','imagen5','imagen6')}
        row.update({'Producto':item['producto'],'Categoría':item['categoria'],'País':item['pais'],
                    'Fuente':item['fuente'],'Motivo de tendencia':item['motivo_tendencia']})
        row.update({f'precio_{source}':item['precios'][source] for source in ('amazon','ebay','aliexpress')})
        row.update({f'búsqueda_{source}':item['busquedas'][source] for source in ('amazon','ebay','aliexpress')})
        rows.append(row)
    return rows
