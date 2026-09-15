from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class EmailLoginTest(TestCase):
    def setUp(self):
        self.password = "una-clave-segura"
        self.user = User.objects.create_user(
            email="persona@example.com",
            first_name="Ana",
            last_name="Pérez",
            password=self.password,
        )

    def test_login_uses_email_case_insensitively(self):
        response = self.client.post(
            reverse("login"),
            {"email": "PERSONA@EXAMPLE.COM", "password": self.password},
        )

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            self.user.pk,
        )

    def test_invalid_email_or_password_uses_generic_message(self):
        for credentials in (
            {"email": "no-es-un-correo", "password": self.password},
            {"email": self.user.email, "password": "incorrecta"},
        ):
            with self.subTest(credentials=credentials):
                response = self.client.post(
                    reverse("login"), credentials, follow=True
                )
                self.assertContains(
                    response,
                    "Usuario o contraseña incorrectos.",
                )

    def test_login_page_exposes_email_field_not_username(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, 'name="email"')
        self.assertNotContains(response, 'name="username"')

    def test_logout_ends_the_session(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)
