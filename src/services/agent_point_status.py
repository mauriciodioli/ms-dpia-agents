"""Read existing point balances and calendar budgets; never creates or spends points."""
import json
from datetime import datetime,timedelta,time,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from services.scraping_quota import cupos,operaciones,HELD


def period_window(period,zone,now):
    now=now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    tz=ZoneInfo(zone);day=now.astimezone(tz).date()
    if period in ('week','SEMANA'):
        start=day-timedelta(days=day.weekday());end=start+timedelta(days=7);kind='week'
    elif period in ('month','MES'):
        start=day.replace(day=1);end=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1);kind='month'
    else:raise ValueError('unsupported_budget_period')
    utc=lambda d:datetime.combine(d,time.min,tz).astimezone(timezone.utc).replace(tzinfo=None)
    return dict(key=f'{kind}:{start.isoformat()}:{zone}',start=utc(start),end=utc(end))


def context(row):
    value=row.get('contexto_json')
    try:value=json.loads(value) if isinstance(value,str) else value
    except (ValueError,TypeError):return {}
    return value if isinstance(value,dict) else {}


def cost(row):
    return 0 if row['origen']=='recarga' else 5 if row['origen']=='promocion' else 1


def locked_balance(conn,owner):
    # Locking reads see committed values even with an earlier REPEATABLE READ snapshot.
    total=conn.execute(select(cupos.c.ejecuciones_habilitadas).where(cupos.c.usuario_id==owner).with_for_update()).scalar_one_or_none()
    rows=conn.execute(select(operaciones).where(operaciones.c.usuario_id==owner,operaciones.c.estado.in_(HELD)).with_for_update()).mappings().all()
    return int(total or 0),rows


def point_status(conn,owner,agent_id,limit,period,zone,now):
    window=period_window(period,zone,now);total,rows=locked_balance(conn,owner)
    available=max(0,total-sum(cost(row) for row in rows))
    used=sum(cost(row) for row in rows if agent_id and context(row).get('agent_id')==agent_id and context(row).get('period')==window['key'])
    consumed=sum(cost(row) for row in rows if row['estado']=='consumed' and agent_id and context(row).get('agent_id')==agent_id and context(row).get('period')==window['key'])
    remaining=max(0,limit-used);effective=min(remaining,available)
    return dict(budget=limit,budget_used=used,budget_consumed=consumed,budget_reserved=used-consumed,budget_remaining=remaining,user_available=available,effective_remaining=effective,
        period=window['key'],period_start=window['start'].isoformat()+'Z',period_end=window['end'].isoformat()+'Z',
        color='red' if effective==0 else 'green' if effective*4>limit else 'yellow')
