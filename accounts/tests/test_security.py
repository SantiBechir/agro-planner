from datetime import timedelta

from axes.models import AccessAttempt
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.security import client_ip


class LoginSecurityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "una-clave-segura-123"
        cls.user = get_user_model().objects.create_superuser(
            email="security@example.com", first_name="Security", last_name="Test",
            password=cls.password,
        )

    def fail_logins(self, url, field):
        for _ in range(5):
            response = self.client.post(url, {field: self.user.email, "password": "incorrecta"})
        self.assertEqual(response.status_code, 429)
        return response

    def test_public_login_blocks_correct_password_after_five_failures(self):
        response = self.fail_logins(reverse("login"), "email")
        self.assertEqual(response["Retry-After"], "900")
        response = self.client.post(reverse("login"), {
            "email": self.user.email.upper(), "password": self.password,
        })
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_login_has_same_protection_and_normalizes_email(self):
        self.fail_logins(reverse("admin:login"), "username")
        response = self.client.post(reverse("admin:login"), {
            "username": self.user.email.upper(), "password": self.password,
        })
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_and_public_login_share_lockout(self):
        self.fail_logins(reverse("login"), "email")
        response = self.client.post(reverse("admin:login"), {
            "username": self.user.email, "password": self.password,
        })
        self.assertEqual(response.status_code, 429)

    def test_lockout_expires_and_success_clears_failed_attempts(self):
        self.fail_logins(reverse("login"), "email")
        AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=16))
        response = self.client.post(reverse("login"), {
            "email": self.user.email, "password": self.password,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertFalse(AccessAttempt.objects.exists())

    def test_forged_forwarding_headers_do_not_bypass_default_lockout(self):
        self.fail_logins(reverse("login"), "email")
        response = self.client.post(reverse("login"), {
            "email": self.user.email, "password": self.password,
        }, HTTP_X_REAL_IP="192.0.2.5", HTTP_X_FORWARDED_FOR="192.0.2.6")
        self.assertEqual(response.status_code, 429)

    def test_separate_users_at_same_address_are_not_locked_together(self):
        self.fail_logins(reverse("login"), "email")
        other = get_user_model().objects.create_user(
            email="other@example.com", first_name="Other", last_name="Test", password=self.password,
        )
        response = self.client.post(reverse("login"), {
            "email": other.email, "password": self.password,
        })
        self.assertEqual(response.status_code, 302)

    def test_failed_attempt_logs_do_not_store_password_or_email_in_post_data(self):
        self.client.post(reverse("login"), {"email": self.user.email, "password": "private-password"})
        attempt = AccessAttempt.objects.get()
        self.assertNotIn("private-password", attempt.post_data)
        self.assertNotIn(self.user.email, attempt.post_data)

    def test_login_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("login"), {"email": self.user.email, "password": self.password})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", client.session)

    def test_logout_rejects_get_and_requires_csrf_on_post(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.get(reverse("logout")).status_code, 405)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        self.assertIn("_auth_user_id", client.session)

    def test_private_pages_and_fragments_cannot_be_cached(self):
        self.client.force_login(self.user)
        for url in (reverse("home"), reverse("lote_list"), reverse("admin:index")):
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertIn("no-store", response["Cache-Control"])

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_explicit_proxy_setting_uses_single_valid_real_ip(self):
        factory = RequestFactory()
        self.assertEqual(client_ip(factory.get("/", HTTP_X_REAL_IP="192.0.2.8")), "192.0.2.8")
        self.assertIsNone(client_ip(factory.get("/", HTTP_X_REAL_IP="192.0.2.8, 192.0.2.9")))
