"""Global administrative switches, encrypted settings, diagnostics and audit.

Revision CAS prevents a slow probe from overriding a later disable/configure.
No SQL transaction/row lock is held during provider network diagnostics.
"""
import re
from datetime import timedelta
from uuid import uuid4
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, insert, update
from sqlalchemy.exc import IntegrityError
from . import models as m
from .auth import now_utc
from .contracts import iso
from .errors import EngineError
from .integration_models import integrations, audit
from .provider_transport import ProviderHTTP, probe, validate_scraper_url, SCRAPER_BASE

PROVIDERS = {
    'dpia-scraper': {'provider': 'dpia.scraper', 'tool': 'dpia.amazon.search', 'capability': 'search'},
    'openai': {'provider': 'openai.responses', 'tool': 'openai.analysis', 'capability': 'analysis'},
}
BY_PROVIDER = {v['provider']: k for k, v in PROVIDERS.items()}


def provider_spec(provider):
    if provider not in PROVIDERS:
        raise EngineError('integration_not_found', 404)
    return PROVIDERS[provider]


def require_enabled(conn, provider_id):
    """Linearization point shared with disable. Missing config fails closed."""
    key = BY_PROVIDER.get(provider_id)
    if key is None:
        return
    row = conn.execute(select(integrations.c.enabled).where(integrations.c.id == key).with_for_update()).first()
    if row is None or not row.enabled:
        raise EngineError('integration_disabled', 409)


class IntegrationService:
    def __init__(self, engine, config, *, http=None, clock=now_utc):
        self.engine, self.config, self.clock = engine, config, clock
        self.http = http or ProviderHTTP()

    def cipher(self):
        try:
            key = self.config.get('AGENTS_INTEGRATION_MASTER_KEY', '')
            if not key:
                raise ValueError
            return Fernet(key.encode('ascii'))
        except (ValueError, TypeError, UnicodeError):
            raise EngineError('integration_encryption_unavailable', 503) from None

    def decrypt(self, row):
        try:
            return self.cipher().decrypt(row['credential_ciphertext'].encode('ascii')).decode('utf-8')
        except (InvalidToken, AttributeError, UnicodeError):
            raise EngineError('integration_encryption_unavailable', 503) from None

    def defaults(self, provider):
        provider_spec(provider)
        if provider == 'dpia-scraper':
            return {'base_url': self.config.get('DPIA_SCRAPER_BASE_URL', SCRAPER_BASE),
                    'timeout_seconds': self.config.get('DPIA_SCRAPER_TIMEOUT_SECONDS', 120)}
        return {'model': self.config.get('OPENAI_MODEL', ''), 'timeout_seconds': 60, 'max_output_tokens': 2000}

    def row(self, conn, provider, *, lock=False):
        provider_spec(provider)
        query = select(integrations).where(integrations.c.id == provider)
        row = conn.execute(query.with_for_update() if lock else query).mappings().first()
        return dict(row) if row else dict(id=provider, config=self.defaults(provider), credential_ciphertext=None,
            enabled=False, revision=0, diagnostic={}, checked_at=None, last_success_at=None)

    def valid_config(self, provider, config):
        if provider == 'dpia-scraper':
            if set(config) != {'base_url', 'timeout_seconds'}:
                raise EngineError('invalid_contract')
            config = {**config, 'base_url': validate_scraper_url(config['base_url'],
                self.config.get('DPIA_SCRAPER_ALLOWED_HOSTS', ('api.dpia.site',)))}
            low, high = 90, 180
        else:
            if set(config) != {'model', 'timeout_seconds', 'max_output_tokens'}:
                raise EngineError('invalid_contract')
            model = config['model']
            if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', model):
                raise EngineError('invalid_model')
            allowed = self.config.get('AGENTS_OPENAI_MODELS', ())
            if model not in allowed:
                raise EngineError('model_not_configured')
            if type(config['max_output_tokens']) is not int or not 16 <= config['max_output_tokens'] <= 16000:
                raise EngineError('invalid_contract')
            low, high = 5, 180
        if type(config['timeout_seconds']) is not int or not low <= config['timeout_seconds'] <= high:
            raise EngineError('invalid_contract')
        return config

    def readiness(self, conn, provider, row):
        spec = provider_spec(provider)
        from .tools import default_registry
        tool = default_registry().tools.get(spec['tool'])
        implemented = tool is not None and tool.implementation_status == 'IMPLEMENTED'
        available = any(spec['capability'] in w['capabilities'] for w in conn.execute(select(m.workers).where(
            m.workers.c.heartbeat_at >= self.clock() - timedelta(seconds=60),
            m.workers.c.reported_state.in_(['AVAILABLE', 'BUSY']))).mappings())
        configured = False
        error = None
        if row['credential_ciphertext']:
            try:
                self.valid_config(provider, row['config'])
                self.cipher()  # Validate key availability; status reads never decrypt the token.
                configured = True
            except EngineError as exc:
                error = exc.code
        return dict(configured=configured, adapter_implemented=implemented, worker_available=available,
                    configuration_error=error)

    def public(self, conn, provider, row):
        ready = self.readiness(conn, provider, row)
        diag = row['diagnostic']
        result = dict(id=provider, provider=PROVIDERS[provider]['provider'], capability=PROVIDERS[provider]['capability'],
            config=row['config'], credential_present=bool(row['credential_ciphertext']), enabled=row['enabled'],
            revision=row['revision'], **ready, authenticated=diag.get('authenticated'), healthy=diag.get('healthy'),
            permissions=diag.get('permissions', []), permissions_ok=diag.get('permissions_ok', False),
            last_error=diag.get('error') or ready['configuration_error'],
            checked_at=iso(row['checked_at']), last_success_at=iso(row['last_success_at']),
            latency_ms=diag.get('latency_ms'), marketplaces=diag.get('marketplaces', {}))
        if provider == 'openai':
            result['available_models'] = list(self.config.get('AGENTS_OPENAI_MODELS', ()))
            result['diagnostic_scope'] = 'model_metadata_only'
        else:
            result['diagnostic_scope'] = 'scraper_auth_and_api_only'
        return result

    def get(self, provider):
        with self.engine.connect() as conn:
            return self.public(conn, provider, self.row(conn, provider))

    @staticmethod
    def revision(body):
        if type(body.get('expected_revision')) is not int or body['expected_revision'] < 0:
            raise EngineError('invalid_revision')
        return body['expected_revision']

    def mutate(self, provider, expected, changes, actor, action, reason=None):
        try:
            with self.engine.begin() as conn:
                row = self.row(conn, provider, lock=True)
                if row['revision'] != expected:
                    raise EngineError('revision_conflict', 409)
                values = {**changes, 'revision': expected + 1, 'updated_at': self.clock()}
                if expected == 0:
                    initial = {k: row[k] for k in ('id', 'config', 'credential_ciphertext', 'enabled',
                               'diagnostic', 'checked_at', 'last_success_at')}
                    conn.execute(insert(integrations).values(**(initial | values)))
                else:
                    count = conn.execute(update(integrations).where(integrations.c.id == provider,
                        integrations.c.revision == expected).values(**values)).rowcount
                    if count != 1:
                        raise EngineError('revision_conflict', 409)
                conn.execute(insert(audit).values(id=str(uuid4()), integration_id=provider, actor_id=actor,
                    action=action, revision=expected + 1, reason_code=reason, created_at=self.clock()))
                return self.public(conn, provider, self.row(conn, provider))
        except IntegrityError:
            raise EngineError('revision_conflict', 409) from None

    def save(self, provider, body, actor):
        expected = self.revision(body)
        if set(body) - {'expected_revision', 'config', 'credential'} or not isinstance(body.get('config'), dict):
            raise EngineError('invalid_contract')
        config = self.valid_config(provider, body['config'])
        changes = dict(config=config, enabled=False, diagnostic={}, checked_at=None, last_success_at=None)
        with self.engine.connect() as conn:
            row = self.row(conn, provider)
        secret = body.get('credential')
        if secret is not None:
            if not isinstance(secret, str) or not 10 <= len(secret) <= 4096 or any(c.isspace() or ord(c) < 32 for c in secret):
                raise EngineError('invalid_credential')
            if secret.startswith('dpa_'):
                raise EngineError('wrong_credential_system')
            changes['credential_ciphertext'] = self.cipher().encrypt(secret.encode('utf-8')).decode('ascii')
        elif not row['credential_ciphertext']:
            raise EngineError('credential_required')
        else:
            self.decrypt(row)  # Do not silently retain an undecryptable secret.
        return self.mutate(provider, expected, changes, actor, 'CONFIGURED')

    def diagnose(self, provider, body, actor, *, enable=False):
        expected = self.revision(body)
        if set(body) != {'expected_revision'}:
            raise EngineError('invalid_contract')
        with self.engine.connect() as conn:
            row = self.row(conn, provider)
            if row['revision'] != expected:
                raise EngineError('revision_conflict', 409)
            ready = self.readiness(conn, provider, row)
        if not ready['configured']:
            diag = dict(authenticated=None, healthy=False, permissions=[], permissions_ok=False,
                        error=ready['configuration_error'] or 'integration_not_configured', latency_ms=None)
        else:
            try:
                diag = probe(provider, row['config'], self.decrypt(row), self.http)
            except EngineError as error:
                diag = dict(authenticated=None, healthy=False, permissions=[], permissions_ok=False,
                            error=error.code, latency_ms=None)
        changes = dict(diagnostic=diag, checked_at=self.clock())
        successful = diag['healthy'] and diag['authenticated'] and diag['permissions_ok']
        if successful:
            changes['last_success_at'] = self.clock()
        error = diag['error']
        # Availability is rechecked after network I/O; CAS protects concurrent disable/save.
        with self.engine.connect() as conn:
            ready = self.readiness(conn, provider, row)
        if enable:
            error = error or ('adapter_not_implemented' if not ready['adapter_implemented'] else
                              'worker_unavailable' if not ready['worker_available'] else None)
            changes['enabled'] = bool(successful and error is None)
        result = self.mutate(provider, expected, changes, actor,
            'ENABLE_REJECTED' if enable and error else 'ENABLED' if enable else 'TESTED', error)
        return result, error

    def disable(self, provider, body, actor):
        expected = self.revision(body)
        if set(body) != {'expected_revision'}:
            raise EngineError('invalid_contract')
        return self.mutate(provider, expected, {'enabled': False}, actor, 'DISABLED')
