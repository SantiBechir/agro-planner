from functools import wraps

from django.contrib.auth.models import Group, Permission
from django.apps import apps
from django.core.exceptions import PermissionDenied


EDITOR_ROLE = "Editor"
READER_ROLE = "Lector"
FUNCTIONAL_ROLES = (EDITOR_ROLE, READER_ROLE)

PLANNING_MODELS = {"planificacion", "asignacionloteslot"}


def _expected_permissions():
    core_permissions = Permission.objects.filter(content_type__app_label="core")
    reader_permissions = core_permissions.filter(
        codename__startswith="view_"
    ) | core_permissions.filter(codename="add_planificacion")
    editor_permissions = reader_permissions | core_permissions.filter(
        codename__regex=r"^(add|change|delete)_",
    ).exclude(content_type__model__in=PLANNING_MODELS)
    return reader_permissions.distinct(), editor_permissions.distinct()


def sync_functional_roles():
    """Create and reconcile AgroPlanner's two managed functional groups."""
    required_permissions = {
        (model._meta.model_name, f"{action}_{model._meta.model_name}")
        for model in apps.get_app_config("core").get_models()
        for action in ("add", "change", "delete", "view")
    }
    existing_permissions = set(
        Permission.objects.filter(content_type__app_label="core").values_list(
            "content_type__model", "codename"
        )
    )
    if not required_permissions.issubset(existing_permissions):
        return False

    reader_permissions, editor_permissions = _expected_permissions()
    for name, expected in (
        (READER_ROLE, reader_permissions),
        (EDITOR_ROLE, editor_permissions),
    ):
        group, _ = Group.objects.get_or_create(name=name)
        external_permissions = group.permissions.exclude(
            content_type__app_label="core"
        )
        group.permissions.set([*external_permissions, *expected])
    return True


def sync_functional_roles_after_migrate(sender, **kwargs):
    if sender.label == "core":
        sync_functional_roles()


def set_functional_role(user, role_name):
    if role_name not in (*FUNCTIONAL_ROLES, None, ""):
        raise ValueError("Rol funcional inválido.")
    functional_groups = Group.objects.filter(name__in=FUNCTIONAL_ROLES)
    user.groups.remove(*functional_groups)
    if role_name:
        group, _ = Group.objects.get_or_create(name=role_name)
        user.groups.add(group)


def has_editor_access(user):
    return bool(
        user.is_authenticated
        and (user.is_superuser or user.groups.filter(name=EDITOR_ROLE).exists())
    )


def editor_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not has_editor_access(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped
