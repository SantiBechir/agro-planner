"""HTTP local para Docker; usar únicamente con docker-compose.local.yml."""

from .production import *

# El Compose local mantiene el puerto publicado exclusivamente en loopback.
# Se conservan DEBUG=False, la clave fuerte y las protecciones de la aplicación.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
CSRF_TRUSTED_ORIGINS = []
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_PROXY_SSL_HEADER = None
TRUST_PROXY_CLIENT_IP = False
