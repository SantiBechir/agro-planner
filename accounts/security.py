"""Login monitoring for the public login and Django admin."""

from ipaddress import ip_address

from django.conf import settings
from django.http import HttpResponse


def login_identifier(request, credentials=None):
    data = credentials or request.POST
    # Django admin uses 'username' even with an email-based user model.
    return (data.get("email") or data.get("username") or "").strip().lower()[:254]


def client_ip(request):
    raw = request.META.get("REMOTE_ADDR")
    if settings.TRUST_PROXY_CLIENT_IP:
        raw = request.META.get("HTTP_X_REAL_IP") or raw
    try:
        return str(ip_address(raw))
    except (ValueError, TypeError):
        return None


def lockout_response(request, original_response=None, credentials=None):
    response = HttpResponse(
        "Demasiados intentos de inicio de sesión. Intentá nuevamente en 15 minutos.",
        status=429,
        content_type="text/plain; charset=utf-8",
    )
    response["Retry-After"] = "900"
    return response
