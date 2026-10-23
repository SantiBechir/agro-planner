"""Límites personales; no se copian plantillas globales ni datos del archivo de excel."""
from core.models import Campania, Cultivo, LimiteSuperficieCultivoCampania
from core.services.authorization import require_authenticated


def limites_para_usuario(usuario):
    require_authenticated(usuario)
    personales = LimiteSuperficieCultivoCampania.objects.filter(usuario=usuario)
    existentes = set(personales.values_list("cultivo_id", "campania_id"))
    campanias = list(Campania.objects.all())
    faltantes = [
        LimiteSuperficieCultivoCampania(
            usuario=usuario, cultivo=cultivo, campania=campania,
            min_ha=0.0, max_ha=500.0,
        )
        for cultivo in Cultivo.objects.all()
        for campania in campanias
        if (cultivo.pk, campania.pk) not in existentes
    ]
    if faltantes:
        LimiteSuperficieCultivoCampania.objects.bulk_create(faltantes, ignore_conflicts=True)
    return personales
