"""Provider routes only: preserve the existing password-login quota endpoints."""
from django.urls import include, path
from django.views.generic.base import RedirectView
from allauth.urls import build_provider_urlpatterns

urlpatterns = [
    path('3rdparty/', include('allauth.socialaccount.urls')),
    path('login/', RedirectView.as_view(pattern_name='login'), name='account_login'),
    path('signup/', RedirectView.as_view(pattern_name='register'), name='account_signup'),
] + build_provider_urlpatterns()
