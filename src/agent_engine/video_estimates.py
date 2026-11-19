"""Account/resource-specific administrative evidence for provider estimates.

No built-in price and no inference from changes in wallet balance.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from sqlalchemy import select
from .integration_models import integrations
from .errors import EngineError
from .video_costs import positive


def validate_tariffs(values):
    if not isinstance(values,list) or len(values)>100:raise EngineError('invalid_contract')
    required={'provider_id','provider_revision','engine','avatar_id','voice_id','aspect_ratio',
              'usd_per_second','valid_until','reference','account_id','resolution','voice_engine','voice_model'}
    for value in values:
        if not isinstance(value,dict) or not required<=set(value) or set(value)-required-{'provisional','authorized_job_id','avatar_type','voice_mode'}:raise EngineError('invalid_contract')
        if 'provisional' in value and type(value['provisional']) is not bool:raise EngineError('invalid_contract')
        if 'authorized_job_id' in value and not isinstance(value['authorized_job_id'],str):raise EngineError('invalid_contract')
        if 'avatar_type' in value and (value['avatar_type'] not in ('photo_avatar','video_avatar','studio_avatar') or value['avatar_id']!='auto'):
            raise EngineError('invalid_contract')
        if 'voice_mode' in value and (value['voice_mode'] not in ('instant','professional') or value['voice_id']!='auto'):
            raise EngineError('invalid_contract')
        if any(not isinstance(value[k],str) or (not value[k] and k!='voice_model') or len(value[k])>2048 for k in required-{'provider_revision'}):raise EngineError('invalid_contract')
        if type(value['provider_revision']) is not int or value['provider_revision']<1:raise EngineError('invalid_contract')
        positive(value['usd_per_second'],'VIDEO_COST_NOT_VERIFIABLE')
        try:
            datetime.strptime(value['valid_until'],'%Y-%m-%dT%H:%M:%SZ')
            url=urlsplit(value['reference'])
            if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError()
        except ValueError:raise EngineError('invalid_contract') from None
    return values


def estimate(conn,provider,body,duration,now,account,job_id=None,avatar_type=None,voice_mode=None):
    row=conn.execute(select(integrations).where(integrations.c.id=='video-cost-policy').with_for_update()).mappings().first()
    tariffs=validate_tariffs(row['config'].get('heygen_tariffs',[])) if row else []
    if not isinstance(account,dict) or account.get('billing_type')!='wallet' or (account.get('wallet') or {}).get('currency')!='usd':
        raise EngineError('VIDEO_COST_NOT_VERIFIABLE',409)
    matches=[]
    for tariff in tariffs:
        if (tariff['provider_id']==provider['id'] and tariff['provider_revision']==provider['revision']
            and tariff['account_id']==account.get('username') and tariff['resolution']==body['resolution']
            and tariff['voice_engine']==body['voice_settings']['engine_settings']['engine_type']
            and tariff['voice_model']==body['voice_settings']['engine_settings'].get('model','')
            and tariff['engine']==body['engine']['type'] and tariff['aspect_ratio']==body['aspect_ratio']
            and (tariff.get('avatar_type')==avatar_type if tariff.get('avatar_type') else tariff['avatar_id']==body['avatar_id'])
            and (tariff.get('voice_mode')==voice_mode if tariff.get('voice_mode') else tariff['voice_id']==body['voice_id'])
            and datetime.strptime(tariff['valid_until'],'%Y-%m-%dT%H:%M:%SZ')>now):matches.append(tariff)
    if len(matches)!=1:raise EngineError('VIDEO_COST_NOT_VERIFIABLE',409)
    tariff=matches[0]
    estimated=positive(tariff['usd_per_second'],'VIDEO_COST_NOT_VERIFIABLE')*Decimal(duration)
    try:
        balance=(account.get('wallet') or {}).get('remaining_balance')
        if isinstance(balance,bool) or balance is None:raise InvalidOperation()
        balance=Decimal(str(balance))
        if not balance.is_finite() or balance<0:raise InvalidOperation()
    except (InvalidOperation,ValueError,TypeError):
        raise EngineError('VIDEO_COST_NOT_VERIFIABLE',409) from None
    if balance<estimated:raise EngineError('VIDEO_PROVIDER_BALANCE_INSUFFICIENT',409)
    return {'account_id':account['username'],'estimated_usd':str(estimated),
            'reference':tariff['reference'],'policy_revision':row['revision'],'duration_seconds':duration,
            'usd_per_second':tariff['usd_per_second'],'valid_until':tariff['valid_until'],'confirmed':False,
            'provisional':tariff.get('provisional',False)}
