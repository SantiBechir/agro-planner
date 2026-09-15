"""Política de acceso para las entradas de escritura de la aplicación."""

from django.core.exceptions import PermissionDenied

from accounts.roles import has_editor_access


def require_editor(actor):
    if not has_editor_access(actor):
        raise PermissionDenied


def require_authenticated(actor):
    if not actor.is_authenticated:
        raise PermissionDenied
