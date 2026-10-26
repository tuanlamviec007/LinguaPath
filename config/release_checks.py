"""Read-only startup checks, with bounded, secret-free diagnostic output."""
from ipaddress import ip_address, ip_network
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.db import DatabaseError, connection
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.utils import timezone

from .readiness import SchemaNotReady, check_schema_ready


VERSION = 'linguapath-release-check-v1'
_HEADER = re.compile(r'^HTTP_[A-Z0-9_]+$')
_LABEL = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')


def _host(value):
    if (not isinstance(value, str) or not value or value != value.strip()
            or '*' in value or 'replace_with' in value.casefold() or len(value) > 253):
        return False
    if value.startswith('[') and value.endswith(']'):
        try:
            return ip_address(value[1:-1]).version == 6
        except ValueError:
            return False
    name = value.removeprefix('.').removesuffix('.')
    return bool(name and all(_LABEL.fullmatch(label) for label in name.split('.')))


def _origin(value):
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        port = parts.port
        explicit_host = '[' + hostname + ']' if hostname and ':' in hostname else hostname
        return bool(parts.scheme == 'https' and hostname and not hostname.startswith('.') and _host(explicit_host)
            and not parts.username and not parts.password and not parts.path
            and not parts.query and not parts.fragment and (port is None or 1 <= port <= 65535))
    except (ValueError, TypeError):
        return False


def evaluate_release(*, require_production=True):
    """Return local readiness or strict production prerequisites, without repair.

    ``ready`` covers these checks only. It does not certify ingress, actual
    PostgreSQL concurrency/restore, Docker, reviewer approval or production QA.
    """
    if type(require_production) is not bool:
        raise ValueError('require_production must be a boolean')
    checks = []
    def add(check_id, status, message):
        checks.append({'id': check_id, 'status': status, 'message': message})
    def check(check_id, condition, success, failure):
        add(check_id, 'pass' if condition else 'fail', success if condition else failure)

    if require_production:
        check('debug_disabled', settings.DEBUG is False,
            'Debug output is disabled.', 'Production requires DEBUG=false.')
        check('postgresql_backend', connection.vendor == 'postgresql',
            'The configured database backend is PostgreSQL.', 'Production requires PostgreSQL.')
        secret = getattr(settings, 'SECRET_KEY', None)
        check('secret_key', isinstance(secret, str) and len(secret) >= 50
              and secret != 'dev-only-insecure-key-change-before-deployment',
            'A non-default production secret is configured.', 'Configure a non-default production secret of at least 50 characters.')
        check('secure_cookies', settings.SESSION_COOKIE_SECURE is True and settings.CSRF_COOKIE_SECURE is True,
            'Session and CSRF cookies require HTTPS.', 'Session and CSRF cookies must require HTTPS.')
        check('https_redirect', settings.SECURE_SSL_REDIRECT is True,
            'HTTP-to-HTTPS redirects are enabled.', 'Production requires HTTPS redirects.')
        hosts = getattr(settings, 'ALLOWED_HOSTS', None)
        check('allowed_hosts', type(hosts) in (list, tuple) and bool(hosts) and all(_host(host) for host in hosts),
            'Host configuration has explicit valid entries.', 'Configure explicit valid allowed hosts without wildcards or placeholders.')
        origins = getattr(settings, 'CSRF_TRUSTED_ORIGINS', None)
        check('csrf_origins', type(origins) in (list, tuple) and all(_origin(value) for value in origins),
            'Trusted CSRF origins are explicit HTTPS origins, or same-origin defaults apply.',
            'Trusted CSRF origins must be explicit HTTPS origins without wildcards or placeholders.')
        proxy_ssl = getattr(settings, 'SECURE_PROXY_SSL_HEADER', None)
        check('proxy_ssl_header', proxy_ssl is None or proxy_ssl == ('HTTP_X_FORWARDED_PROTO', 'https'),
            'TLS proxy header configuration matches the supported contract.',
            'TLS proxy header configuration does not match the supported contract.')
        header = getattr(settings, 'AUTH_RATE_LIMIT_CLIENT_IP_HEADER', '')
        proxies = getattr(settings, 'AUTH_RATE_LIMIT_TRUSTED_PROXIES', ())
        proxy_valid = isinstance(header, str) and type(proxies) in (tuple, list)
        networks = []
        if proxy_valid:
            try:
                networks = [ip_network(value) for value in proxies]
                proxy_valid = all(network.prefixlen > 0 for network in networks)
            except (TypeError, ValueError):
                proxy_valid = False
        if proxy_valid and header:
            proxy_valid = bool(_HEADER.fullmatch(header) and networks)
        check('auth_proxy_configuration', proxy_valid,
            'Client-IP forwarding is disabled or constrained to explicit trusted peers.',
            'Forwarded client IPs require a valid header and explicit bounded proxy networks.')
        add('ingress_verification', 'warning',
            'Actual ingress peers and forwarded-header behavior require staging verification; configuration is not proof of trust.')
        if isinstance(header, str) and not header:
            add('auth_peer_fallback', 'warning',
                'Authentication quotas currently use the socket peer; verify client separation behind the deployed proxy.')
            if networks:
                add('unused_auth_proxies', 'warning', 'Trusted proxy networks are configured while client-IP forwarding is disabled.')
        hsts = getattr(settings, 'SECURE_HSTS_SECONDS', 0)
        add('hsts', 'pass' if type(hsts) is int and hsts > 0 else 'warning',
            'HSTS is configured.' if type(hsts) is int and hsts > 0 else 'HSTS is not enabled; choose the rollout policy before public deployment.')
        enabled = getattr(settings, 'AI_TUTOR_ENABLED', None)
        if enabled is False:
            add('ai_configuration', 'pass', 'Tutor inference is disabled; no provider calls are needed for startup.')
        elif enabled is True:
            from learning.ai_provider import provider_name, tutor_ai_available
            limits = [getattr(settings, key, None) for key in ('AI_TUTOR_DAILY_LIMIT',
                'AI_TUTOR_MINUTE_LIMIT', 'AI_TUTOR_GLOBAL_DAILY_LIMIT', 'AI_TUTOR_GLOBAL_MINUTE_LIMIT')]
            try:
                available = provider_name() in ('openai', 'cloudflare') and tutor_ai_available()
            except (TypeError, ValueError, AttributeError):
                available = False
            check('ai_configuration', available and all(type(value) is int and 0 <= value <= 2147483647 for value in limits),
                'Enabled Tutor inference has valid provider configuration and bounded quotas.',
                'Enabled Tutor inference requires valid provider configuration and bounded integer quotas.')
        else:
            add('ai_configuration', 'fail', 'Tutor inference enablement must be a boolean.')
    else:
        add('production_configuration', 'skipped', 'Local mode does not assess production settings or infrastructure.')

    schema_ready = False
    try:
        check_schema_ready()
        schema_ready = True
        add('database_schema', 'pass', 'Database connectivity, migrations and required tables are ready.')
    except (DatabaseError, SchemaNotReady, InconsistentMigrationHistory):
        add('database_schema', 'fail', 'Database/schema is unavailable or migrations are incomplete; run the reviewed release procedure.')
    if schema_ready:
        from learning.management.commands.check_weak_word_outcomes import projection_ready
        try:
            check('weak_word_projection', projection_ready(),
                'Submitted quiz history has ready projection metadata and receipts.',
                'Weak-word projection needs an explicit reviewed backfill before serving traffic.')
        except DatabaseError:
            add('weak_word_projection', 'fail', 'Projection metadata could not be checked; verify the database before starting traffic.')
    else:
        add('weak_word_projection', 'skipped', 'Projection metadata cannot be checked before schema readiness.')
    blocked = [item['id'] for item in checks if item['status'] == 'fail']
    return {'version': VERSION, 'checked_at': timezone.now().isoformat(),
        'mode': 'production' if require_production else 'local', 'ready': not blocked,
        'blocked': blocked, 'checks': checks, 'release_approval': False,
        'scope': 'Read-only configuration/schema/projection prerequisites only; not evidence of ingress, PostgreSQL concurrency/restore, Docker, professional content approval or complete audit acceptance.'}
