"""HTTPS awareness for a verified, single-hop reverse proxy.

No forwarded headers are trusted by default. Configure only the actual peer IPs
seen by WSGI, after verifying that Nginx overwrites X-Forwarded-Proto with $scheme
and preserves the public Host header. Never use X-Forwarded-For as the peer.
"""
from ipaddress import ip_address
from werkzeug.middleware.proxy_fix import ProxyFix


class TrustedSchemeProxy:
    def __init__(self, app, trusted_ips):
        self.app = app
        self.trusted_ips = frozenset(ip_address(value.strip()) for value in trusted_ips if value.strip())
        self.forwarded = ProxyFix(app, x_for=0, x_proto=1, x_host=0, x_port=0, x_prefix=0)

    def __call__(self, environ, start_response):
        try:
            trusted = ip_address(environ.get('REMOTE_ADDR', '')) in self.trusted_ips
        except ValueError:
            trusted = False
        # The verified proxy must overwrite this with one scheme, not append a
        # client-controlled chain. Other forwarded values never change WSGI.
        if trusted and environ.get('HTTP_X_FORWARDED_PROTO') in ('http', 'https'):
            return self.forwarded(environ, start_response)
        return self.app(environ, start_response)


def configure_proxy(app):
    configured = app.config.get('AGENTS_TRUSTED_PROXY_IPS', '')
    if configured.strip():
        app.wsgi_app = TrustedSchemeProxy(app.wsgi_app, configured.split(','))
