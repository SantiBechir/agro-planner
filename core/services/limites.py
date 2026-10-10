"""Límites de superficie personales para las planificaciones."""

from django.db import transaction

from core.models import Campania, Cultivo, LimiteSuperficieCultivoCampania


def limites_para_usuario(usuario):
    """Devuelve la configuración privada del usuario, creándola desde la plantilla.

    Las filas sin ``usuario`` son la configuración base importada desde Excel.
    Nunca se modifican cuando una persona edita sus propios límites.
    """
    personales = LimiteSuperficieCultivoCampania.objects.filter(usuario=usuario)
    existentes = set(personales.values_list("cultivo_id", "campania_id"))
    plantillas = {
        (plantilla.cultivo_id, plantilla.campania_id): plantilla
        for plantilla in LimiteSuperficieCultivoCampania.objects.filter(
            usuario__isnull=True
        ).select_related("cultivo", "campania")
    }
    faltantes = []
    for cultivo in Cultivo.objects.all():
        for campania in Campania.objects.all():
            clave = (cultivo.pk, campania.pk)
            if clave in existentes:
                continue
            plantilla = plantillas.get(clave)
            faltantes.append(
                LimiteSuperficieCultivoCampania(
                    usuario=usuario,
                    cultivo=cultivo,
                    campania=campania,
                    min_ha=plantilla.min_ha if plantilla else 0.0,
                    max_ha=plantilla.max_ha if plantilla else 500.0,
                )
            )
    if faltantes:
        with transaction.atomic():
            LimiteSuperficieCultivoCampania.objects.bulk_create(
                faltantes, ignore_conflicts=True
            )
    return LimiteSuperficieCultivoCampania.objects.filter(usuario=usuario)