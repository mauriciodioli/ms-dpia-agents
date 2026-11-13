"""UTC scheduling with explicit rejection of DST gaps and ambiguous local times."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .errors import EngineError


def local_utc(local: datetime, zone: ZoneInfo) -> datetime:
    candidates = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) == local:
            candidates.add(candidate.replace(tzinfo=None))
    if len(candidates) != 1:
        raise EngineError('ambiguous_or_nonexistent_local_time')
    return candidates.pop()


def next_occurrence(definition: dict, after: datetime) -> datetime | None:
    # Compare local civil times; local_utc rejects DST gaps and folds.
    zone = ZoneInfo(definition['timezone'])
    local_after = after.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
    hour, minute = map(int, definition['execution_time'].split(':'))
    if definition['frequency'] == 'ONCE':
        local = datetime.fromisoformat(definition['execution_date'] + 'T' + definition['execution_time'])
        candidate = local_utc(local, zone)
        return candidate if candidate > after else None
    for offset in range(371):
        date = local_after.date() + timedelta(days=offset)
        if definition['frequency'] == 'WEEKLY' and date.isoweekday() not in definition['weekdays']:
            continue
        local = datetime(date.year, date.month, date.day, hour, minute)
        if local <= local_after:
            continue
        candidate = local_utc(local, zone)
        if candidate > after:
            return candidate
    raise EngineError('schedule_out_of_range')


def delivery_time(definition: dict, execution: datetime) -> datetime:
    zone = ZoneInfo(definition['timezone'])
    local = execution.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
    hour, minute = map(int, definition['delivery_time'].split(':'))
    due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due < local:
        due += timedelta(days=1)
    return local_utc(due, zone)
