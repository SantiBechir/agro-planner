"""Carga y eliminación del historial productivo de un lote."""

from django.core.exceptions import ValidationError
from datetime import date, timedelta
from math import isfinite
from django.db import transaction

from core.models import CampaniaHistorica, Cultivo, HistorialLoteCultivo, Lote
from core.services.authorization import require_editor


def estacion_de_cultivo(cultivo):
    """Devuelve la estación según el inicio real de la ventana de siembra.

    ``siembra_inicio`` es el día relativo al 1 de junio definido en el input.
    En el calendario productivo utilizado por la aplicación, las siembras de
    febrero a agosto son de invierno y las de septiembre a enero, de verano.
    No se usa ``tipo``: los conjuntos I_P e I_S del Excel no representan
    estaciones (por ejemplo, Trigo y Colza pertenecen a I_P).
    """
    try:
        inicio = int(cultivo.siembra_inicio)
    except (TypeError, ValueError):
        return None

    fecha_inicio = date(2025, 6, 1) + timedelta(days=inicio - 1)
    return "invierno" if fecha_inicio.month in (2, 3, 4, 5, 6, 7, 8) else "verano"


def _parse_rendimiento(raw):
    if not raw:
        return None
    try:
        valor = float(raw)
        if not isfinite(valor) or valor < 0:
            raise ValueError
        return valor
    except (TypeError, ValueError) as exc:
        raise ValidationError("El rendimiento debe ser un número válido mayor o igual a cero.") from exc


def cargar_historial(actor, lote_id, *, anio_inicio, cultivo_1_id,
                     rendimiento_1="", cultivo_2_id=None, rendimiento_2=""):
    require_editor(actor)
    lote = Lote.objects.get(pk=lote_id)
    base_year = CampaniaHistorica.anio_base_actual()
    try:
        anio = int(anio_inicio)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Debe indicar la campaña y el cultivo principal.") from exc
    if anio > base_year - 1:
        raise ValidationError("La campaña debe ser anterior a la campaña actual.")
    if anio < base_year - 15:
        raise ValidationError(
            f"La campaña debe estar dentro de las últimas 15 campañas "
            f"(desde {base_year - 15}/{base_year - 14})."
        )

    try:
        cultivo_1 = Cultivo.objects.filter(pk=int(cultivo_1_id)).first()
        cultivo_2 = Cultivo.objects.filter(pk=int(cultivo_2_id)).first() if cultivo_2_id else None
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError("Seleccione cultivos válidos.") from exc
    if cultivo_1 is None:
        raise ValidationError("Debe indicar la campaña y el cultivo principal.")
    if cultivo_2_id and cultivo_2 is None:
        raise ValidationError("El segundo cultivo no es válido.")
    if cultivo_2 is not None and cultivo_2.pk == cultivo_1.pk:
        raise ValidationError("El segundo cultivo debe ser distinto del primero.")
    if cultivo_2 is not None:
        estacion_1 = estacion_de_cultivo(cultivo_1)
        estacion_2 = estacion_de_cultivo(cultivo_2)
        if estacion_1 is None or estacion_2 is None:
            raise ValidationError(
                "Solo se pueden combinar cultivos de invierno y verano en una campaña."
            )
        if estacion_1 == estacion_2:
            raise ValidationError(
                "Una campaña no puede tener dos cultivos de "
                f"{estacion_1}. Seleccione uno de invierno y uno de verano."
            )

    with transaction.atomic():
        campania, _ = CampaniaHistorica.objects.get_or_create(
            anio_inicio=anio, defaults={"codigo": f"CH{anio}"},
        )
        HistorialLoteCultivo.objects.filter(lote=lote, campania_historica=campania).delete()
        registros = [HistorialLoteCultivo(
            lote=lote, cultivo=cultivo_1, campania_historica=campania,
            presente=True, rendimiento_kg_ha=_parse_rendimiento(rendimiento_1),
        )]
        if cultivo_2 is not None:
            registros.append(HistorialLoteCultivo(
                lote=lote, cultivo=cultivo_2, campania_historica=campania,
                presente=True, rendimiento_kg_ha=_parse_rendimiento(rendimiento_2),
            ))
        HistorialLoteCultivo.objects.bulk_create(registros)
    return campania, lote


def eliminar_historial(actor, lote_id, *, anio_inicio):
    require_editor(actor)
    lote = Lote.objects.get(pk=lote_id)
    eliminados, _ = HistorialLoteCultivo.objects.filter(
        lote=lote, campania_historica__anio_inicio=anio_inicio,
    ).delete()
    return eliminados
