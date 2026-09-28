"""Avoid storing login pages, private data and HTMX fragments in shared caches."""

from django.conf import settings
from django.utils.cache import add_never_cache_headers


class PrivateResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith(settings.STATIC_URL):
            add_never_cache_headers(response)
            response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if getattr(settings, "CONTENT_SECURITY_POLICY", ""):
                response.setdefault("Content-Security-Policy", settings.CONTENT_SECURITY_POLICY)
        return response
