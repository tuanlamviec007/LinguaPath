"""Render-specific settings; the local and Cloudflare settings stay unchanged."""
import base64
import binascii
import hashlib
import os
import re

from django.core.exceptions import ImproperlyConfigured

# Render's generated secrets contain 32 random bytes encoded as 44 characters.
# Derive a stable domain-separated key meeting the application's 50-char gate;
# entropy remains 256 bits. Never generate a fresh session key on each restart.
if not os.environ.get('DJANGO_SECRET_KEY'):
    try:
        seed = base64.b64decode(os.environ.get('DJANGO_SECRET_SEED', ''), validate=True)
    except (ValueError, binascii.Error):
        seed = b''
    if len(seed) != 32:
        raise ImproperlyConfigured('Configure a Render-generated secret seed or a production DJANGO_SECRET_KEY.')
    os.environ['DJANGO_SECRET_KEY'] = hashlib.sha512(b'linguapath-render-secret-v1\0' + seed).hexdigest()
    del seed

from .settings import *  # noqa: F403,E402

_render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip().lower()
if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.onrender\.com', _render_host):
    raise ImproperlyConfigured('RENDER_EXTERNAL_HOSTNAME must be the assigned onrender.com hostname.')

_custom_hosts = [host.strip() for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if host.strip()]
ALLOWED_HOSTS = list(dict.fromkeys([_render_host, *_custom_hosts]))
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([f'https://{_render_host}', *CSRF_TRUSTED_ORIGINS]))  # noqa: F405

# Neon supports both direct and pooled PostgreSQL URLs. Disabling server-side
# cursors avoids cursor affinity assumptions if a pooled URL is chosen later.
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':  # noqa: F405
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True  # noqa: F405

# Render accepts 3xx health checks. Ensure probes actually reach the health
# handlers, rather than appearing healthy solely because HTTPS redirected them.
SECURE_REDIRECT_EXEMPT = [r'^livez/$', r'^healthz/$']
