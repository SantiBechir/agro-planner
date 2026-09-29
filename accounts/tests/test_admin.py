from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from accounts.forms import CustomUserCreationForm
from accounts.roles import EDITOR_ROLE, READER_ROLE


User = get_user_model()


class CustomUserAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            first_name="Admin",
            last_name="AgroPlanner",
            password="una-clave-segura",
        )
        self.client.force_login(self.admin)

    def test_add_form_uses_email_name_and_last_name(self):
        response = self.client.get(reverse("admin:accounts_user_add"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="first_name"')
        self.assertContains(response, 'name="last_name"')
        self.assertNotContains(response, 'name="username"')

    def test_change_form_is_available(self):
        response = self.client.get(
            reverse("admin:accounts_user_change", args=[self.admin.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.admin.email)

    def test_admin_add_and_change_select_exactly_one_functional_role(self):
        add_response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "email": "editor@example.com",
                "first_name": "Edith",
                "last_name": "Campo",
                "password1": "una-clave-segura-123",
                "password2": "una-clave-segura-123",
                "is_active": "on",
                "role": EDITOR_ROLE,
                "_save": "Guardar",
            },
        )
        self.assertEqual(add_response.status_code, 302)
        user = User.objects.get(email="editor@example.com")
        self.assertEqual(user.functional_role, EDITOR_ROLE)

        unrelated = Group.objects.create(name="Grupo ajeno")
        user.groups.add(unrelated)
        change_response = self.client.post(
            reverse("admin:accounts_user_change", args=[user.pk]),
            {
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "password": user.password,
                "is_active": "on",
                "role": READER_ROLE,
                "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
                "_save": "Guardar",
            },
        )
        self.assertEqual(
            change_response.status_code,
            302,
            change_response.context["adminform"].form.errors.as_text()
            if change_response.status_code == 200
            else "",
        )
        self.assertEqual(
            set(user.groups.filter(name__in=(EDITOR_ROLE, READER_ROLE)).values_list("name", flat=True)),
            {READER_ROLE},
        )
        self.assertTrue(user.groups.filter(pk=unrelated.pk).exists())

    def test_admin_form_requires_role_for_normal_user_but_not_superuser(self):
        common = {
            "email": "persona2@example.com",
            "first_name": "Ana",
            "last_name": "Pérez",
            "password1": "una-clave-segura-123",
            "password2": "una-clave-segura-123",
        }
        normal_form = CustomUserCreationForm(data=common)
        self.assertFalse(normal_form.is_valid())
        self.assertIn("role", normal_form.errors)

        # The plain creation form does not expose is_superuser; the admin form
        # does, so verify the admin path directly.
        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                **common,
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
                "role": "",
                "_save": "Guardar",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            User.objects.get(email="persona2@example.com").functional_role,
            "Superusuario",
        )
