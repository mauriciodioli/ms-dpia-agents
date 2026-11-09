"""Redis Streams transport. Payloads contain identifiers only; no business data."""
from dataclasses import dataclass
import re
from uuid import UUID
from .errors import EngineError


@dataclass(frozen=True)
class TaskMessage:
    owner_id: int
    job_id: str
    task_id: str
    outbox_id: str

    @classmethod
    def parse(cls, fields):
        try:
            data = {(k.decode() if isinstance(k, bytes) else k):
                    (v.decode() if isinstance(v, bytes) else v) for k, v in fields.items()}
            if set(data) != {'owner_id', 'job_id', 'task_id', 'outbox_id'}:
                raise ValueError
            owner = int(data['owner_id'])
            if owner <= 0 or str(owner) != data['owner_id']:
                raise ValueError
            for key in ('job_id', 'task_id', 'outbox_id'):
                if str(UUID(data[key])) != data[key]:
                    raise ValueError
            return cls(owner, data['job_id'], data['task_id'], data['outbox_id'])
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise EngineError('invalid_stream_message') from None


class RedisStreams:
    def __init__(self, client, *, prefix='ms-dpia-agents', group='agents-v1'):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', prefix) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', group):
            raise EngineError('invalid_stream_namespace')
        self.client, self.prefix, self.group = client, prefix, group
        self.cursors = {}

    @classmethod
    def from_config(cls, config):
        if not config.get('REDIS_HOST'):
            raise EngineError('redis_not_configured', 503)
        import redis  # Lazy: web startup neither imports the client nor connects.
        client = redis.Redis(host=config['REDIS_HOST'], port=config.get('REDIS_PORT', 6379),
            db=config.get('REDIS_DB', 0), password=config.get('REDIS_PASSWORD') or None,
            socket_connect_timeout=3, socket_timeout=3, decode_responses=True)
        return cls(client, prefix=config.get('AGENT_ENGINE_STREAM_PREFIX', 'ms-dpia-agents'))

    def key(self, capability):
        if not re.fullmatch(r'[a-z][a-z0-9_.-]{0,79}', capability):
            raise EngineError('invalid_capability')
        return self.prefix+':tasks:'+capability

    def ensure_group(self, capability):
        try:
            self.client.xgroup_create(self.key(capability), self.group, id='0-0', mkstream=True)
        except Exception as error:
            # BUSYGROUP is the sole tolerated response; never expose Redis errors.
            if str(error).split(' ', 1)[0] != 'BUSYGROUP':
                raise EngineError('redis_unavailable', 503) from None

    def publish(self, capability, message):
        try:
            value = self.client.xadd(self.key(capability), {
                'owner_id': str(message.owner_id), 'job_id': message.job_id,
                'task_id': message.task_id, 'outbox_id': message.outbox_id})
            return value.decode('ascii') if isinstance(value, bytes) else value
        except Exception:
            raise EngineError('redis_publish_unconfirmed', 503) from None

    def read(self, capability, consumer, *, count=1):
        try:
            rows = self.client.xreadgroup(self.group, consumer,
                {self.key(capability): '>'}, count=count, block=100)
            return [entry for stream, entries in rows for entry in entries]
        except Exception:
            raise EngineError('redis_unavailable', 503) from None

    def reclaim(self, capability, consumer, *, idle_ms=30000, count=10):
        key = self.key(capability)
        try:
            result = self.client.xautoclaim(key, self.group, consumer, idle_ms,
                start_id=self.cursors.get(key, '0-0'), count=count)
            self.cursors[key] = result[0]
            # Redis 6.2 returns two elements; >=7 may also return deleted IDs.
            return result[1]
        except Exception:
            raise EngineError('redis_recovery_unavailable', 503) from None

    def ack(self, capability, message_id):
        try:
            return self.client.xack(self.key(capability), self.group, message_id)
        except Exception:
            raise EngineError('redis_ack_unconfirmed', 503) from None
