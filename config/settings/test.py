"""Isolated SQLite test settings; never use the development or deployed database."""

import os

os.environ.setdefault("SECRET_KEY", "agro-planner-isolated-tests-only-never-use-in-production")

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
TRUST_PROXY_CLIENT_IP = False
