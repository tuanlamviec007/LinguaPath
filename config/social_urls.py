"""Provider routes only: preserve existing password-login quota endpoints."""
from django.conf import settings
from django.shortcuts import render
from django.urls import include, path
from django.views.generic.base import RedirectView


def provider_unavailable(request):
    return render(request, 'socialaccount/provider_unavailable.html', status=503)


urlpatterns = [
    path('3rdparty/', include('allauth.socialaccount.urls')),
    path('login/', RedirectView.as_view(pattern_name='login'), name='account_login'),
    path('signup/', RedirectView.as_view(pattern_name='register'), name='account_signup'),
]
for provider in ('google', 'facebook'):
    app = settings.SOCIALACCOUNT_PROVIDERS.get(provider, {}).get('APP', {})
    if app.get('client_id') and app.get('secret'):
        urlpatterns.append(path('', include(f'allauth.socialaccount.providers.{provider}.urls')))
    else:
        urlpatterns += [
            path(f'{provider}/login/', provider_unavailable, name=f'{provider}_login'),
            path(f'{provider}/login/callback/', provider_unavailable, name=f'{provider}_callback'),
        ]
