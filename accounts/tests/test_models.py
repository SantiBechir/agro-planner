from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, transaction
from django.test import TestCase


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
