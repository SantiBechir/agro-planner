from .base import *
from decouple import config
import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from urllib.parse import urlparse

DEBUG = False


def _normalize_host(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""

    if "://" in value:
        value = urlparse(value).netloc
    else:
        value = value.split("/", 1)[0]

    if "@" in value:
        value = value.split("@", 1)[1]
    if ":" in value:
        value = value.split(":", 1)[0]
    return value.strip()


def _normalize_origin(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""

    candidate = value if "://" in value else f"https://{value}"
    parsed = urlparse(candidate)
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"

raw_allowed_hosts = config("ALLOWED_HOSTS", default="")
railway_public_domain = config("RAILWAY_PUBLIC_DOMAIN", default="")

ALLOWED_HOSTS = [
    host
    for host in (_normalize_host(raw_host) for raw_host in raw_allowed_hosts.split(","))
    if host
]

normalized_railway_domain = _normalize_host(railway_public_domain)
if normalized_railway_domain and normalized_railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(normalized_railway_domain)

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "Missing ALLOWED_HOSTS environment variable. Set ALLOWED_HOSTS or provide RAILWAY_PUBLIC_DOMAIN."
    )

raw_csrf_trusted_origins = config("CSRF_TRUSTED_ORIGINS", default="")
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in (
        _normalize_origin(raw_origin)
        for raw_origin in raw_csrf_trusted_origins.split(",")
    )
    if origin
]
if normalized_railway_domain:
    railway_origin = _normalize_origin(normalized_railway_domain)
    if railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_origin)

database_url = config("DATABASE_URL", default="")
if not database_url:
    raise ImproperlyConfigured(
        "Missing DATABASE_URL environment variable. Attach a PostgreSQL service in Railway."
    )

DATABASES = {
    "default": dj_database_url.parse(
        database_url,
        conn_max_age=600,
        ssl_require=True,
    )
}

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_MANIFEST_STRICT = config("WHITENOISE_MANIFEST_STRICT", default=False, cast=bool)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
