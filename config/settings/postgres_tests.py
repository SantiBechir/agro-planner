"""Pruebas PostgreSQL explícitas, sin usar la base de desarrollo o producción."""
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .test import *

_test_url = os.environ.get("TEST_DATABASE_URL", "")
if not _test_url:
    raise ImproperlyConfigured("TEST_DATABASE_URL debe apuntar a un servidor PostgreSQL de pruebas.")
DATABASES = {"default": dj_database_url.parse(_test_url, conn_max_age=0)}
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("TEST_DATABASE_URL debe usar PostgreSQL.")
