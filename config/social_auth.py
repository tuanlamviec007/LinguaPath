"""Configuration-only provider visibility; never query SocialApp on public pages."""
from django.conf import settings


def provider_buttons(request):
    providers = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {})
    enabled = getattr(settings, 'SOCIAL_AUTH_ENABLED', False)
    return {'google_login_ready': enabled and bool(providers.get('google', {}).get('APP')),
            'facebook_login_ready': enabled and bool(providers.get('facebook', {}).get('APP'))}


# Imported only for an enabled OAuth rollout; ordinary boots keep allauth optional.
if getattr(settings, 'SOCIAL_AUTH_ENABLED', False):
    from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

    class SocialAdapter(DefaultSocialAccountAdapter):
        def save_user(self, request, sociallogin, form=None):
            from django.db import transaction
            from planner.models import LearnerProfile
            with transaction.atomic():
                user = super().save_user(request, sociallogin, form)
                LearnerProfile.objects.get_or_create(user=user)
                return user
