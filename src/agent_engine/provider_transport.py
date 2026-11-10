"""Bounded HTTPS transport and verified read-only provider diagnostics.

Never return/log response bodies or exception text on failure. No redirects,
ambient proxy credentials, automatic POST retries, or calls at import time.
"""
import json
import time
from urllib.parse import urlsplit, quote
import requests
from .errors import EngineError

SCRAPER_BASE = 'https://api.dpia.site/api/scraper/v1'
OPENAI_BASE = 'https://api.openai.com/v1'
REQUIRED_PERMISSIONS = frozenset({'scraper:read', 'scraper:write'})
HTTP_ERRORS = {400: 'provider_invalid_request', 401: 'invalid_credentials',
               403: 'insufficient_permissions', 404: 'provider_resource_unavailable',
               409: 'provider_conflict', 410: 'provider_resource_expired',
               415: 'provider_invalid_content', 429: 'provider_rate_limited',
               502: 'provider_unavailable', 503: 'provider_unavailable'}


def validate_scraper_url(url, allowed_hosts=('api.dpia.site',)):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in allowed_hosts or
                parsed.port not in (None, 443) or parsed.username or parsed.password or
                parsed.query or parsed.fragment or parsed.path.rstrip('/') != '/api/scraper/v1'):
            raise ValueError
        # Reconstruct: no user-controlled query, port, path or alternate authority.
        return 'https://' + parsed.hostname + '/api/scraper/v1'
    except (ValueError, TypeError, AttributeError):
        raise EngineError('invalid_provider_url') from None


class ProviderHTTP:
    def request(self, method, url, secret, *, timeout, params=None, body=None, max_bytes=1048576):
        started = time.monotonic()
        try:
            with requests.Session() as session:
                session.trust_env = False
                with session.request(method, url, headers={'Authorization': 'Bearer ' + secret,
                        'Accept': 'application/json', 'Content-Type': 'application/json'},
                        params=params, json=body, timeout=(min(5, timeout), timeout),
                        allow_redirects=False, stream=True) as response:
                    if response.status_code != 200:
                        raise EngineError(HTTP_ERRORS.get(response.status_code, 'provider_unavailable'), 502)
                    chunks, length = [], 0
                    for chunk in response.iter_content(16384):
                        length += len(chunk)
                        if length > max_bytes or time.monotonic() - started > timeout + 5:
                            raise EngineError('provider_response_limit', 502)
                        chunks.append(chunk)
                    data = json.loads(b''.join(chunks))
                    if not isinstance(data, dict):
                        raise EngineError('provider_invalid_response', 502)
                    return data
        except requests.Timeout:
            raise EngineError('provider_timeout', 504) from None
        except requests.RequestException:
            raise EngineError('provider_unavailable', 502) from None
        except (ValueError, UnicodeError):
            raise EngineError('provider_invalid_response', 502) from None


def scraper_auth(data):
    token = data.get('token')
    if (data.get('success') is not True or data.get('mecanismo') != 'database' or
            not isinstance(token, dict) or token.get('activo') is not True or
            token.get('estado') != 'activo' or not isinstance(token.get('permisos'), list) or
            any(not isinstance(x, str) for x in token['permisos'])):
        raise EngineError('provider_invalid_response', 502)
    # Whitelist only permission names. Never pass token metadata to callers.
    return sorted(REQUIRED_PERMISSIONS.intersection(token['permisos']))


def probe(provider, config, secret, http):
    start = time.monotonic()
    result = dict(authenticated=None, healthy=False, permissions=[], permissions_ok=False,
                  error=None, marketplaces={})
    try:
        timeout = min(config['timeout_seconds'], 10)
        if provider == 'dpia-scraper':
            base = config['base_url']
            auth = http.request('GET', base + '/auth/check', secret, timeout=timeout,
                                params={'permiso': 'scraper:read'})
            result['permissions'] = scraper_auth(auth)
            result['authenticated'] = True
            auth = http.request('GET', base + '/auth/check', secret, timeout=timeout,
                                params={'permiso': 'scraper:write'})
            permissions = scraper_auth(auth)
            result['permissions'] = permissions
            result['permissions_ok'] = REQUIRED_PERMISSIONS.issubset(permissions)
            if not result['permissions_ok']:
                raise EngineError('insufficient_permissions', 403)
            health = http.request('GET', base + '/estado', secret, timeout=timeout)
            if health.get('success') is not True or health.get('api') != 'scraper' or health.get('version') != 'v1':
                raise EngineError('provider_invalid_response', 502)
            markets = http.request('GET', base + '/marketplaces', secret, timeout=timeout)
            if markets.get('success') is not True or not isinstance(markets.get('datos'), dict):
                raise EngineError('provider_invalid_response', 502)
            for name in ('amazon', 'ebay', 'aliexpress', 'mercadolibre'):
                row = markets['datos'].get(name)
                if row is None:
                    continue
                domains = row.get('domains') if isinstance(row, dict) else None
                if not isinstance(domains, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in domains.items()):
                    raise EngineError('provider_invalid_response', 502)
                # Country identifiers only; never echo arbitrary external metadata.
                countries = [c for c in ('argentina', 'italia', 'espana', 'polonia', 'mexico', 'uruguay') if c in domains]
                result['marketplaces'][name] = countries
        else:
            model = http.request('GET', OPENAI_BASE + '/models/' + quote(config['model'], safe=''), secret, timeout=timeout)
            if model.get('object') != 'model' or model.get('id') != config['model']:
                raise EngineError('provider_invalid_response', 502)
            result.update(authenticated=True, permissions=['models:retrieve'], permissions_ok=True)
        result['healthy'] = True
    except EngineError as error:
        result['error'] = error.code
        if error.code == 'invalid_credentials':
            result['authenticated'] = False
        if error.code == 'insufficient_permissions':
            result['permissions_ok'] = False
    result['latency_ms'] = round((time.monotonic() - start) * 1000, 2)
    return result
