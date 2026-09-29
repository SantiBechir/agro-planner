from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    use_in_migrations = True

    def normalize_email(self, email):
        return super().normalize_email(email).strip().lower()

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email.strip())

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("El correo electrónico es obligatorio.")
        if not extra_fields.get("first_name"):
            raise ValueError("El nombre es obligatorio.")
        if not extra_fields.get("last_name"):
            raise ValueError("El apellido es obligatorio.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superusuario debe tener is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superusuario debe tener is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField("correo electrónico", unique=True)
    first_name = models.CharField("nombre", max_length=150)
    last_name = models.CharField("apellido", max_length=150)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_ci_unique",
            )
        ]

    def save(self, *args, **kwargs):
        self.email = User.objects.normalize_email(self.email)
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.email

    @property
    def functional_role(self):
        from .roles import EDITOR_ROLE, READER_ROLE

        if self.is_superuser:
            return "Superusuario"
        roles = set(
            self.groups.filter(name__in=(EDITOR_ROLE, READER_ROLE)).values_list(
                "name", flat=True
            )
        )
        return EDITOR_ROLE if EDITOR_ROLE in roles else READER_ROLE

    @property
    def can_edit_agricultural_data(self):
        from .roles import has_editor_access

        return has_editor_access(self)

    def __str__(self):
        return self.email
