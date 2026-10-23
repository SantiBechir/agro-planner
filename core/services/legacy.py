"""Asignación explícita y atómica de datos anteriores sin propietario."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import ConfiguracionCultivoUsuario, Costo, Cultivo, LimiteSuperficieCultivoCampania
from core.services.authorization import require_authenticated


@transaction.atomic
def asignar_datos_legacy(usuario):
    require_authenticated(usuario)
    get_user_model().objects.select_for_update().get(pk=usuario.pk)
    costos = list(Costo.objects.select_for_update(of=("self",)).filter(usuario__isnull=True).select_related("lote"))
    limites = list(LimiteSuperficieCultivoCampania.objects.select_for_update().filter(usuario__isnull=True))
    if not costos and not limites:
        return 0, 0
    keys = set()
    for costo in costos:
        key = (costo.cultivo_id, costo.tipo_costo_id, costo.campania_id, costo.lote_id)
        if key in keys or Costo.objects.filter(
            usuario=usuario, cultivo_id=key[0], tipo_costo_id=key[1], campania_id=key[2], lote_id=key[3],
        ).exists():
            raise ValidationError("Hay costos duplicados o conflictos con los costos personales. No se asignó ningún dato.")
        if costo.lote_id and costo.lote.usuario_id != usuario.pk:
            raise ValidationError("Un costo antiguo apunta a un lote que no pertenece al destinatario.")
        keys.add(key)
    keys = set()
    for limite in limites:
        key = (limite.cultivo_id, limite.campania_id)
        if key in keys or LimiteSuperficieCultivoCampania.objects.filter(
            usuario=usuario, cultivo_id=key[0], campania_id=key[1],
        ).exists():
            raise ValidationError("Hay límites duplicados o conflictos con los límites personales. No se asignó ningún dato.")
        keys.add(key)
    if ConfiguracionCultivoUsuario.objects.filter(usuario=usuario).exists():
        raise ValidationError("El destinatario ya tiene habilitaciones personales. No se asignó ningún dato.")
    Costo.objects.filter(pk__in=[obj.pk for obj in costos]).update(usuario=usuario)
    LimiteSuperficieCultivoCampania.objects.filter(pk__in=[obj.pk for obj in limites]).update(usuario=usuario)
    ConfiguracionCultivoUsuario.objects.bulk_create([
        ConfiguracionCultivoUsuario(usuario=usuario, cultivo=cultivo,
                                    habilitado_optimizacion=cultivo.habilitado_optimizacion)
        for cultivo in Cultivo.objects.all()
    ])
    return len(costos), len(limites)
