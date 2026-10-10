"""Solicitud de trabajos; la ejecución permanece en el worker existente."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from core.models import (
    CompatibilidadCultivoSuelo,

    Lote,
    Planificacion,
)
from core.services.authorization import require_authenticated
from core.services.limites import limites_para_usuario


def _hay_combinacion_de_superficies(lotes, objetivo):
    """Indica si alguna combinación de lotes completos alcanza ``objetivo``."""
    alcanzables = {0.0}
    for lote in lotes:
        superficie = float(lote.superficie_ha)
        nuevos = {
            round(acumulado + superficie, 6)
            for acumulado in alcanzables
            if acumulado + superficie <= objetivo + 1e-6
        }
        alcanzables.update(nuevos)
    return any(abs(superficie - objetivo) <= 1e-6 for superficie in alcanzables)


def _validar_lotes_habilitados(actor):
    """Detecta mínimos de superficie imposibles antes de enviar el solver."""
    lotes = list(Lote.objects.filter(usuario=actor, habilitado=True).select_related("tipo_suelo"))
    if not lotes:
        raise ValidationError(
            "Debe habilitar al menos un lote para ejecutar la planificación."
        )

    compatibles = set(
        CompatibilidadCultivoSuelo.objects.filter(compatible=True).values_list(
            "cultivo_id", "tipo_suelo_id"
        )
    )
    limites = limites_para_usuario(actor).filter(
        min_ha__gt=0,
        cultivo__habilitado_optimizacion=True,
    ).select_related("cultivo", "campania")

    minimos_por_campania = {}
    for limite in limites:
        lotes_compatibles = [
            lote
            for lote in lotes
            if (limite.cultivo_id, lote.tipo_suelo_id) in compatibles
        ]
        superficie_compatible = sum(
            lote.superficie_ha
            for lote in lotes_compatibles
        )
        if superficie_compatible + 1e-9 < limite.min_ha:
            raise ValidationError(
                f"No se puede planificar {limite.cultivo.nombre} en "
                f"{limite.campania.codigo}: configuraste un mínimo de "
                f"{limite.min_ha:g} ha, pero solo tenés "
                f"{superficie_compatible:g} ha habilitadas y compatibles. "
                "Reducí el mínimo o habilitá/agregá más superficie compatible."
            )
        minimos_por_campania[limite.campania] = (
            minimos_por_campania.get(limite.campania, 0.0) + limite.min_ha
        )
        if (
            limite.cultivo.no_repetir_sin_intermedio
            and abs(limite.min_ha - limite.max_ha) <= 1e-9
            and not _hay_combinacion_de_superficies(
                lotes_compatibles, limite.min_ha
            )
        ):
            raise ValidationError(
                f"No se puede planificar {limite.cultivo.nombre} en "
                f"{limite.campania.codigo}: configuraste exactamente "
                f"{limite.min_ha:g} ha, pero ninguna combinación de lotes "
                "compatibles alcanza esa superficie. Ajustá el límite o los lotes."
            )

    superficie_total = sum(lote.superficie_ha for lote in lotes)
    for campania, minimo_total in minimos_por_campania.items():
        capacidad = superficie_total * campania.slots.count()
        if minimo_total > capacidad + 1e-9:
            raise ValidationError(
                f"No se puede planificar la campaña {campania.codigo}: los mínimos "
                f"de cultivos suman {minimo_total:g} ha, pero tus lotes habilitados "
                f"permiten como máximo {capacidad:g} ha en esa campaña."
            )


def solicitar_planificacion(actor, *, nombre):
    require_authenticated(actor)
    nombre = (nombre or "").strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError("Ingrese un nombre de hasta 100 caracteres.")
    _validar_lotes_habilitados(actor)
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
            nombre=nombre, usuario=actor, estado=Planificacion.Estado.PENDIENTE,
        )
