"""Authentication quotas run in process_view after CSRF has accepted the POST."""
from ipaddress import ip_address, ip_network
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.http import HttpResponse
from django.utils.cache import add_never_cache_headers
from django.utils.deprecation import MiddlewareMixin

from learning.auth_limits import AuthReservationConflict, canonical_ip, reserve_auth_request


logger = logging.getLogger(__name__)
LIMIT_MESSAGE = 'Bạn đang thao tác quá nhanh. Vui lòng đợi một lúc rồi thử lại.'
UNAVAILABLE_MESSAGE = 'Tạm thời chưa thể xử lý yêu cầu này. Vui lòng thử lại sau.'


def client_ip(request):
    remote = canonical_ip(request.META.get('REMOTE_ADDR', ''))
    proxies = getattr(settings, 'AUTH_RATE_LIMIT_TRUSTED_PROXIES', ())
    header = getattr(settings, 'AUTH_RATE_LIMIT_CLIENT_IP_HEADER', '')
    if isinstance(proxies, str) or not isinstance(proxies, (tuple, list)) or not isinstance(header, str):
        raise ImproperlyConfigured('Invalid authentication trusted-proxy configuration')
    try:
        networks = [ip_network(value) for value in proxies]
    except (ValueError, TypeError):
        raise ImproperlyConfigured('Invalid authentication trusted-proxy configuration') from None
    if header and (not header.startswith('HTTP_') or not header.replace('_', '').isalnum()):
        raise ImproperlyConfigured('Invalid authentication client-IP header')
    if header and remote and any(ip_address(remote) in network for network in networks):
        forwarded = canonical_ip(request.META.get(header, ''))
        if forwarded:
            return forwarded
    # An invalid/missing forwarded value never becomes an attacker-controlled
    # bucket. The trusted socket address still provides a conservative quota.
    return remote or 'unknown'


def _response(message, status, retry_after):
    result = HttpResponse(message, status=status, content_type='text/plain; charset=utf-8')
    result['Retry-After'] = str(retry_after)
    add_never_cache_headers(result)
    return result


class AuthThrottleMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != 'POST' or request.resolver_match is None:
            return None
        match = request.resolver_match
        if match.namespace == 'admin' and match.url_name == 'login':
            action = 'admin_login'
        elif not match.namespace and match.url_name in ('login', 'register', 'password_reset'):
            action = match.url_name
        else:
            return None
        # A missing/misordered CSRF middleware must fail closed rather than
        # spending quota or allowing an unprotected authentication attempt.
        if not getattr(request, 'csrf_processing_done', False):
            logger.warning('Authentication throttling requires prior CSRF validation')
            return _response(UNAVAILABLE_MESSAGE, 503, 30)
        try:
            identifier = request.POST.get('email' if action == 'password_reset' else 'username', '')
            decision = reserve_auth_request(action, client_ip(request), identifier)
        except AuthReservationConflict:
            return _response(LIMIT_MESSAGE, 429, 1)
        except (DatabaseError, ImproperlyConfigured):
            # Do not log identifiers, client addresses, POST data, or exception
            # details, which could include connection credentials.
            logger.warning('Authentication throttling unavailable; request denied')
            return _response(UNAVAILABLE_MESSAGE, 503, 30)
        if not decision.allowed:
            return _response(LIMIT_MESSAGE, 429, decision.retry_after)
        return None
