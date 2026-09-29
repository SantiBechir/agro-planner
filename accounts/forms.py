from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import User
from .roles import EDITOR_ROLE, FUNCTIONAL_ROLES, READER_ROLE, set_functional_role


ROLE_CHOICES = (("", "---------"), (EDITOR_ROLE, EDITOR_ROLE), (READER_ROLE, READER_ROLE))


class FunctionalRoleFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            current_roles = self.instance.groups.filter(
                name__in=FUNCTIONAL_ROLES
            ).values_list("name", flat=True)
            self.fields["role"].initial = next(iter(current_roles), "")

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("is_superuser") and not cleaned_data.get("role"):
            self.add_error("role", "El rol es obligatorio para usuarios normales.")
        return cleaned_data

    def _save_m2m(self):
        super()._save_m2m()
        set_functional_role(self.instance, self.cleaned_data.get("role"))


class CustomUserCreationForm(FunctionalRoleFormMixin, UserCreationForm):
    role = forms.ChoiceField(label="Rol", choices=ROLE_CHOICES, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name")


class CustomUserChangeForm(FunctionalRoleFormMixin, UserChangeForm):
    role = forms.ChoiceField(label="Rol", choices=ROLE_CHOICES, required=False)

    class Meta:
        model = User
        fields = "__all__"
