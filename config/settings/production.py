from .base import *
from decouple import config
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

DEBUG = False

raw_allowed_hosts = config("ALLOWED_HOSTS", default="")
railway_public_domain = config("RAILWAY_PUBLIC_DOMAIN", default="")

ALLOWED_HOSTS = [host.strip() for host in raw_allowed_hosts.split(",") if host.strip()]
if railway_public_domain and railway_public_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(railway_public_domain)

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "Missing ALLOWED_HOSTS environment variable. Set ALLOWED_HOSTS or provide RAILWAY_PUBLIC_DOMAIN."
    )

raw_csrf_trusted_origins = config("CSRF_TRUSTED_ORIGINS", default="")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in raw_csrf_trusted_origins.split(",")
    if origin.strip()
]
if railway_public_domain:
    railway_origin = f"https://{railway_public_domain}"
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

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
