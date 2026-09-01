from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .forms import CustomUserCreationForm
from .roles import (
    EDITOR_ROLE,
    READER_ROLE,
    set_functional_role,
    sync_functional_roles,
)


User = get_user_model()


class UserManagerTest(TestCase):
    def test_create_user_normalizes_email_and_has_no_username(self):
        user = User.objects.create_user(
            email="  Persona@Example.COM  ",
            first_name="Ana",
            last_name="Pérez",
            password="una-clave-segura",
        )

        self.assertEqual(user.email, "persona@example.com")
        self.assertEqual(user.display_name, "Ana Pérez")
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("username")

    def test_email_is_unique_case_insensitively(self):
        User.objects.create_user(
            email="persona@example.com",
            first_name="Ana",
            last_name="Pérez",
            password="una-clave-segura",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                email="PERSONA@example.com",
                first_name="Otra",
                last_name="Persona",
                password="otra-clave-segura",
            )

    def test_email_name_and_last_name_are_required(self):
        required_values = (
            {"email": "", "first_name": "Ana", "last_name": "Pérez"},
            {"email": "ana@example.com", "first_name": "", "last_name": "Pérez"},
            {"email": "ana@example.com", "first_name": "Ana", "last_name": ""},
        )

        for values in required_values:
            with self.subTest(values=values), self.assertRaises(ValueError):
                User.objects.create_user(password="una-clave-segura", **values)

    def test_create_superuser_sets_required_flags(self):
        user = User.objects.create_superuser(
            email="admin@example.com",
            first_name="Admin",
            last_name="AgroPlanner",
            password="una-clave-segura",
        )

        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_display_name_falls_back_to_email(self):
        user = User(
            email="persona@example.com",
            first_name="",
            last_name="",
        )

        self.assertEqual(user.display_name, "persona@example.com")


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


class FunctionalRoleSyncTest(TestCase):
    def test_post_migrate_creates_both_groups_automatically(self):
        self.assertTrue(Group.objects.filter(name=EDITOR_ROLE).exists())
        self.assertTrue(Group.objects.filter(name=READER_ROLE).exists())

    def test_sync_waits_until_all_core_permissions_exist(self):
        Group.objects.filter(name__in=(EDITOR_ROLE, READER_ROLE)).delete()
        Permission.objects.filter(
            content_type__app_label="core", codename="view_lote"
        ).delete()

        self.assertFalse(sync_functional_roles())
        self.assertFalse(
            Group.objects.filter(name__in=(EDITOR_ROLE, READER_ROLE)).exists()
        )

    def test_sync_creates_expected_permissions_and_excludes_planning_mutation(self):
        Group.objects.filter(name__in=(EDITOR_ROLE, READER_ROLE)).delete()
        self.assertTrue(sync_functional_roles())

        reader = Group.objects.get(name=READER_ROLE)
        editor = Group.objects.get(name=EDITOR_ROLE)
        reader_codes = set(reader.permissions.filter(content_type__app_label="core").values_list("codename", flat=True))
        editor_codes = set(editor.permissions.filter(content_type__app_label="core").values_list("codename", flat=True))

        all_view_codes = set(
            Permission.objects.filter(
                content_type__app_label="core", codename__startswith="view_"
            ).values_list("codename", flat=True)
        )
        self.assertEqual(reader_codes, all_view_codes | {"add_planificacion"})
        self.assertTrue({"add_lote", "change_costo", "delete_cultivo"} <= editor_codes)
        self.assertTrue(all_view_codes <= editor_codes)
        self.assertNotIn("change_planificacion", editor_codes)
        self.assertNotIn("delete_planificacion", editor_codes)
        self.assertNotIn("add_asignacionloteslot", editor_codes)

    def test_sync_is_idempotent_removes_stale_core_permissions_and_preserves_external(self):
        sync_functional_roles()
        reader = Group.objects.get(name=READER_ROLE)
        stale = Permission.objects.get(
            content_type__app_label="core", codename="delete_planificacion"
        )
        external = Permission.objects.get(
            content_type__app_label="auth", codename="view_group"
        )
        reader.permissions.add(stale, external)

        sync_functional_roles()
        first_ids = set(reader.permissions.values_list("pk", flat=True))
        sync_functional_roles()
        second_ids = set(reader.permissions.values_list("pk", flat=True))

        self.assertEqual(first_ids, second_ids)
        self.assertNotIn(stale.pk, second_ids)
        self.assertIn(external.pk, second_ids)

    def test_role_mapping_removes_other_functional_role_only(self):
        user = User.objects.create_user(
            email="roles@example.com",
            first_name="Rita",
            last_name="Roles",
            password="una-clave-segura",
        )
        unrelated = Group.objects.create(name="Grupo externo")
        user.groups.add(unrelated)
        set_functional_role(user, EDITOR_ROLE)
        set_functional_role(user, READER_ROLE)

        self.assertEqual(user.functional_role, READER_ROLE)
        self.assertTrue(user.groups.filter(pk=unrelated.pk).exists())
