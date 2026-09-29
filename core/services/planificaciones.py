"""Solicitud de trabajos; la ejecución permanece en el worker existente."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from core.models import Planificacion
from core.services.authorization import require_authenticated


def solicitar_planificacion(actor, *, nombre):
    require_authenticated(actor)
    nombre = (nombre or "").strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError("Ingrese un nombre de hasta 100 caracteres.")
    with transaction.atomic():
        if connection.vendor == "postgresql":
            # Serialize admission across all web workers without locking solver jobs.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [800031])
        active = Planificacion.objects.filter(estado__in=(
            Planificacion.Estado.PENDIENTE, Planificacion.Estado.EJECUTANDO,
        )).count()
        if active >= settings.MAX_ACTIVE_PLANIFICATIONS:
            raise ValidationError("Hay demasiadas planificaciones en espera. Intentá cuando termine alguna.")
        return Planificacion.objects.create(
            nombre=nombre, estado=Planificacion.Estado.PENDIENTE,
        )
