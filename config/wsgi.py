import os

from django.core.wsgi import get_wsgi_application
from pathlib import Path

if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if (PROJECT_ROOT / "config" / "settings" / "local.py").exists():
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

application = get_wsgi_application()
