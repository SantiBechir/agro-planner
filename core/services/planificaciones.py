"""Solicitud de trabajos; la ejecución permanece en el worker existente."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction, models

from core.models import (
    CompatibilidadCultivoSuelo,
    ConfiguracionCultivoUsuario,
    Costo,
    Cultivo,
    Lote,
    Planificacion,
)
from core.services.authorization import require_authenticated
from core.services.limites import limites_para_usuario
from core.services.optimization_inputs import build_pyomo_input_data
from core.services.planificacion_escenario import validar_seleccion, congelar_entradas


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

    if not ConfiguracionCultivoUsuario.objects.filter(
        usuario=actor, habilitado_optimizacion=True,
    ).exists():
        raise ValidationError("Debe habilitar al menos un cultivo para ejecutar la planificación.")

    if Costo.objects.filter(
        usuario=actor, configurado=False,
        cultivo__configuraciones_usuario__usuario=actor,
        cultivo__configuraciones_usuario__habilitado_optimizacion=True,
    ).exists():
        raise ValidationError("Hay precios o costos pendientes de revisar para los cultivos habilitados.")

    compatibles = set(
        CompatibilidadCultivoSuelo.objects.filter(compatible=True).values_list(
            "cultivo_id", "tipo_suelo_id"
        )
    )
    limites = limites_para_usuario(actor).filter(
        min_ha__gt=0,
        cultivo__configuraciones_usuario__usuario=actor,
        cultivo__configuraciones_usuario__habilitado_optimizacion=True,
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


def _validar_escenario(actor, escenario, data):
    pendientes = Costo.objects.filter(
        usuario=actor, configurado=False, cultivo_id__in=escenario["cultivos"],
    ).filter(models.Q(campania_id__in=escenario["campanias"]) | models.Q(campania__isnull=True))
    pendientes = pendientes.filter(models.Q(lote_id__in=escenario["lotes"]) | models.Q(lote__isnull=True))
    if pendientes.exists():
        raise ValidationError("Hay precios o costos pendientes de revisar para los cultivos y campañas seleccionados.")
    lotes = list(Lote.objects.filter(usuario=actor, pk__in=escenario["lotes"]))
    cultivos = {obj.codigo: obj for obj in Cultivo.objects.filter(pk__in=escenario["cultivos"])}
    minimos = {}
    for (codigo, campania), minimo in data["minha_dict"].items():
        if minimo <= 0:
            continue
        compatibles = [lote for lote in lotes if sum(
            data["ep_dict"].get((lote.codigo, suelo), 0) *
            data["sueloi_dict"].get((codigo, suelo), 1) for suelo in data["s"]
        ) >= .5]
        if sum(lote.superficie_ha for lote in compatibles) + 1e-9 < minimo:
            raise ValidationError(f"No se puede planificar {cultivos[codigo].nombre} en {campania}: el mínimo de {minimo:g} ha supera la superficie seleccionada compatible.")
        minimos[campania] = minimos.get(campania, 0) + minimo
        if (cultivos[codigo].no_repetir_sin_intermedio and
                abs(minimo - data["maxha_dict"][(codigo, campania)]) <= 1e-9 and
                not _hay_combinacion_de_superficies(compatibles, minimo)):
            raise ValidationError(f"Ninguna combinación de lotes compatibles alcanza exactamente {minimo:g} ha para {cultivos[codigo].nombre}.")
    for campania, minimo in minimos.items():
        if minimo > sum(data["ha"].values()) * len(data["tc_dict"][campania]) + 1e-9:
            raise ValidationError(f"Los mínimos de {campania} superan la capacidad de los lotes seleccionados.")


def solicitar_planificacion(actor, *, nombre, seleccion=None):
    require_authenticated(actor)
    nombre = (nombre or "").strip()
    if not nombre or len(nombre) > 100:
        raise ValidationError("Ingrese un nombre de hasta 100 caracteres.")
    escenario = validar_seleccion(actor, seleccion) if seleccion is not None else None
    if escenario is None:
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
        data = build_pyomo_input_data(actor, escenario=escenario)
        if escenario is not None:
            _validar_escenario(actor, escenario, data)
        return Planificacion.objects.create(
            nombre=nombre, usuario=actor, estado=Planificacion.Estado.PENDIENTE,
            escenario=escenario or {}, datos_entrada=congelar_entradas(data, actor),
        )
