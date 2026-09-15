"""Solicitud de trabajos; la ejecución permanece en el worker existente."""

from core.models import Planificacion
from core.services.authorization import require_authenticated


def solicitar_planificacion(actor, *, nombre):
    require_authenticated(actor)
    return Planificacion.objects.create(
        nombre=nombre, estado=Planificacion.Estado.PENDIENTE,
    )
