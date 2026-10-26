"""Prevent storage of account-specific responses in browsers and proxies."""
from django.utils.cache import add_never_cache_headers, patch_vary_headers


PRIVATE_VIEWS = {
    'dashboard', 'progress', 'learning_goal', 'tutor', 'register', 'login', 'logout',
    'password_change', 'password_change_done', 'password_reset', 'password_reset_done',
    'password_reset_confirm', 'password_reset_complete',
}


class PrivateResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, 'resolver_match', None)
        user = getattr(request, 'user', None)
        if (getattr(user, 'is_authenticated', False)
                or (match and (match.view_name in PRIVATE_VIEWS
                               or 'learning' in match.namespaces or 'admin' in match.namespaces))):
            add_never_cache_headers(response)
            patch_vary_headers(response, ('Cookie',))
        return response
