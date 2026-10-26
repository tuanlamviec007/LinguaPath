"""Atomic, shared-database reservations for public authentication POSTs."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone
from ipaddress import ip_address
from math import ceil
import unicodedata

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .auth_models import AuthRateBucket


DEFAULT_AUTH_RATE_LIMITS = {
    'login': {'window': 600, 'ip': 100, 'identifier': 10},
    'admin_login': {'window': 600, 'ip': 30, 'identifier': 5},
    'register': {'window': 3600, 'ip': 10, 'identifier': 5},
    'password_reset': {'window': 3600, 'ip': 20, 'identifier': 5},
    'privacy_reauth': {'window': 600, 'ip': 30, 'identifier': 5},
}


@dataclass(frozen=True)
class AuthLimitDecision:
    allowed: bool
    retry_after: int = 0


def canonical_ip(value):
    if not isinstance(value, str) or len(value) > 64 or '%' in value:
        return None
    try:
        address = ip_address(value)
    except (ValueError, TypeError):
        return None
    # Treat equivalent socket representations as the same client.
    return str(getattr(address, 'ipv4_mapped', None) or address)


def normalize_identifier(value):
    # Bound normalization work even for invalid, oversized form fields.
    return unicodedata.normalize('NFKC', str(value or '')[:512]).strip().casefold()


def auth_rate_policy(action):
    overrides = getattr(settings, 'AUTH_RATE_LIMITS', {})
    if (action not in DEFAULT_AUTH_RATE_LIMITS or not isinstance(overrides, dict)
            or set(overrides) - set(DEFAULT_AUTH_RATE_LIMITS)):
        raise ImproperlyConfigured('Invalid authentication rate-limit policy')
    configured = overrides.get(action, {})
    if not isinstance(configured, dict) or set(configured) - {'window', 'ip', 'identifier'}:
        raise ImproperlyConfigured('Invalid authentication rate-limit policy')
    policy = {**DEFAULT_AUTH_RATE_LIMITS[action], **configured}
    for field, value in policy.items():
        upper = 86400 if field == 'window' else 100000
        lower = 1 if field == 'window' else 0
        if type(value) is not int or not lower <= value <= upper:
            raise ImproperlyConfigured('Invalid authentication rate-limit policy')
    return policy


def _bucket_key(action, scope, client_ip, identifier, window):
    return salted_hmac(
        'linguapath.auth-rate.v1',
        '\0'.join((action, scope, str(window), client_ip, identifier)),
        algorithm='sha256',
    ).hexdigest()


def _locked_bucket(action, scope, client_ip, identifier, window, start, end):
    bucket, _ = AuthRateBucket.objects.select_for_update().get_or_create(
        bucket_key=_bucket_key(action, scope, client_ip, identifier, window),
        defaults={'action': action, 'scope': scope, 'window_started_at': start,
                  'expires_at': end, 'request_count': 0},
    )
    if bucket.window_started_at < start:
        AuthRateBucket.objects.filter(pk=bucket.pk).update(
            window_started_at=start, expires_at=end, request_count=0,
        )
        bucket.window_started_at, bucket.expires_at, bucket.request_count = start, end, 0
    return bucket


def reserve_auth_request(action, client_ip, identifier='', *, now=None):
    """Consume both quotas together, or neither; no global username lockouts.

    All accepted POSTs, including successful logins, consume quota. Windows are
    fixed UTC windows; changing the window length or SECRET_KEY starts fresh
    buckets. Pair buckets contain the IP, so locking IP then pair is consistent
    across workers and never locks an account across unrelated client IPs.
    """
    policy = auth_rate_policy(action)
    now = now or timezone.now()
    start_seconds = int(now.timestamp()) // policy['window'] * policy['window']
    start = datetime.fromtimestamp(start_seconds, tz=datetime_timezone.utc)
    end = start + timedelta(seconds=policy['window'])
    client_ip = canonical_ip(client_ip) or 'unknown'
    identifier = normalize_identifier(identifier)

    with transaction.atomic():
        ip_bucket = _locked_bucket(action, 'ip', client_ip, '', policy['window'], start, end)
        if ip_bucket.request_count >= policy['ip']:
            return AuthLimitDecision(False, max(1, ceil((ip_bucket.expires_at - now).total_seconds())))
        buckets = [ip_bucket]
        if identifier:
            pair = _locked_bucket(action, 'identifier', client_ip, identifier, policy['window'], start, end)
            if pair.request_count >= policy['identifier']:
                return AuthLimitDecision(False, max(1, ceil((pair.expires_at - now).total_seconds())))
            buckets.append(pair)
        # The row locks serialize production PostgreSQL writers. The conditional
        # updates also prevent a stale count from passing on other backends.
        for bucket in buckets:
            maximum = policy['ip'] if bucket.scope == 'ip' else policy['identifier']
            changed = AuthRateBucket.objects.filter(
                pk=bucket.pk, window_started_at=bucket.window_started_at,
                request_count__lt=maximum,
            ).update(request_count=F('request_count') + 1)
            if not changed:
                # Throwing rolls back an earlier bucket update in this request.
                raise AuthReservationConflict
    return AuthLimitDecision(True)


class AuthReservationConflict(Exception):
    """A quota could not be reserved atomically; callers must deny this POST."""
