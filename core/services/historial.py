"""Carga y eliminación del historial productivo de un lote."""

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import CampaniaHistorica, Cultivo, HistorialLoteCultivo, Lote
from core.services.authorization import require_editor


def _parse_rendimiento(raw):
    if not raw:
        return None
    try:
        valor = float(raw)
        return valor if valor >= 0 else None
    except ValueError:
        return None


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

    cultivo_1 = Cultivo.objects.filter(pk=cultivo_1_id).first()
    cultivo_2 = Cultivo.objects.filter(pk=cultivo_2_id).first() if cultivo_2_id else None
    if cultivo_1 is None:
        raise ValidationError("Debe indicar la campaña y el cultivo principal.")
    if cultivo_2_id and cultivo_2 is None:
        raise ValidationError("El segundo cultivo no es válido.")
    if cultivo_2 is not None and cultivo_2.pk == cultivo_1.pk:
        raise ValidationError("El segundo cultivo debe ser distinto del primero.")

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
