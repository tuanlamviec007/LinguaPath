"""Prevent a false recovery promise until email delivery is configured."""
from django.conf import settings
from django.contrib.auth.views import PasswordResetView
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods


@never_cache
@require_http_methods(['GET', 'POST'])
def password_reset(request):
    if not settings.PASSWORD_RESET_ENABLED:
        return render(request, 'registration/password_reset_unavailable.html', status=503)
    return PasswordResetView.as_view()(request)
