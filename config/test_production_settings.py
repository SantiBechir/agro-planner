"""Check production startup without using a real key or connecting to Postgres."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class ProductionSettingsTest(SimpleTestCase):
    def run_settings(self, *, verify_assets=False, **overrides):
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "SECRET_KEY": secrets.token_urlsafe(64),
            "ALLOWED_HOSTS": "agro.example.edu.ar",
            "CSRF_TRUSTED_ORIGINS": "https://agro.example.edu.ar",
            "RAILWAY_PUBLIC_DOMAIN": "",
            "DATABASE_URL": "postgres://audit:audit@127.0.0.1:5432/audit",
            "DATABASE_SSL_REQUIRE": "false",
            "SECURE_SSL_REDIRECT": "true",
            "SOLVER_TIME_LIMIT": "300",
            "SOLVER_THREADS": "2",
            "MAX_ACTIVE_PLANIFICATIONS": "5",
            **overrides,
        }
        code = (
            "import django,json; django.setup(); "
            "from django.core.management import call_command; "
            "call_command('check',deploy=True,fail_level='WARNING'); "
            "from django.conf import settings; "
            "print(json.dumps({key:getattr(settings,key) for key in "
            "('DEBUG','SESSION_COOKIE_SECURE','CSRF_COOKIE_SECURE','SECURE_SSL_REDIRECT','SECURE_HSTS_SECONDS')}))"
        )
        if verify_assets:
            code = "\n".join((
                "import django,tempfile,json; django.setup()",
                "from django.conf import settings",
                "from django.core.management import call_command",
                "from django.test import Client",
                "with tempfile.TemporaryDirectory() as static_dir:",
                "    settings.STATIC_ROOT=static_dir",
                "    call_command('collectstatic',interactive=False,verbosity=0)",
                "    client=Client()",
                "    response=client.get('/login/',secure=True,HTTP_HOST='agro.example.edu.ar')",
                "    assert response.status_code == 200",
                "    assert response.cookies['csrftoken']['secure']",
                "    assert 'no-store' in response['Cache-Control']",
                "    assert 'max-age=86400' in response['Strict-Transport-Security']",
                "    assert 'frame-ancestors' in response['Content-Security-Policy']",
                "    assert client.get('/login/',HTTP_HOST='agro.example.edu.ar').status_code == 301",
                "    assert client.get('/login/',secure=True,HTTP_HOST='unknown.example').status_code == 400",
                "    assert all(host not in response.content.decode() for host in ('cdn.tailwindcss.com','unpkg.com','cdn.jsdelivr.net'))",
                "    print('Production assets and HTTPS responses verified.')",
            ))
        return subprocess.run(
            [sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
            env=env, text=True, capture_output=True, timeout=30,
        )

    def test_valid_production_configuration_passes_all_deployment_checks(self):
        result = self.run_settings()
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout.splitlines()[-1])
        self.assertFalse(settings["DEBUG"])
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])
        self.assertTrue(settings["CSRF_COOKIE_SECURE"])
        self.assertTrue(settings["SECURE_SSL_REDIRECT"])
        self.assertGreater(settings["SECURE_HSTS_SECONDS"], 0)

    def test_bad_security_configuration_is_rejected(self):
        bad_configs = (
            {"SECRET_KEY": "your-secret-key-here"},
            {"ALLOWED_HOSTS": "*"},
            {"CSRF_TRUSTED_ORIGINS": "http://agro.example.edu.ar"},
            {"CSRF_TRUSTED_ORIGINS": "https://*.example.edu.ar"},
            {"SECURE_SSL_REDIRECT": "false"},
            {"SOLVER_TIME_LIMIT": "nan"},
            {"SOLVER_THREADS": "0"},
            {"MAX_ACTIVE_PLANIFICATIONS": "0"},
        )
        for config in bad_configs:
            with self.subTest(config=config):
                self.assertNotEqual(self.run_settings(**config).returncode, 0)

    def test_collected_assets_and_https_login_response(self):
        result = self.run_settings(verify_assets=True)
        self.assertEqual(result.returncode, 0, result.stderr)
