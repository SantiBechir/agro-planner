"""Operaciones de lotes y ambientes, independientes de la interfaz HTTP."""

import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from core.models import Ambiente, Lote, TipoSuelo
from core.services.authorization import require_editor


def _next_lote_codigo():
    max_n = 0
    for codigo in Lote.objects.values_list("codigo", flat=True):
        match = re.fullmatch(r"J(\d+)", codigo or "")
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"J{max_n + 1}"


def validar_ambientes(ambientes):
    """Recibe una secuencia de (suelo_id, rendimiento, superficie)."""
    if not ambientes:
        raise ValidationError("Debe cargar al menos un ambiente para el lote.")
    suelos = {str(s.pk): s for s in TipoSuelo.objects.all()}
    vistos = set()
    data = []
    for suelo_id, rendimiento, ha_raw in ambientes:
        suelo_id = str(suelo_id)
        if suelo_id not in suelos:
            raise ValidationError("Cada ambiente debe tener un tipo de suelo válido.")
        if suelo_id in vistos:
            raise ValidationError("No puede repetir el mismo tipo de suelo en dos ambientes del lote.")
        vistos.add(suelo_id)
        if rendimiento not in ("A", "M", "B"):
            raise ValidationError("El rendimiento esperado debe ser Alto, Medio o Bajo.")
        try:
            ha = float(ha_raw)
            if ha <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValidationError("La superficie de cada ambiente debe ser un número mayor a cero.") from exc
        data.append((suelos[suelo_id], rendimiento, ha))
    return data


def _validar_lote(nombre, ambientes, *, lote_id=None):
    # El nombre conserva prioridad sobre los errores de ambientes en el formulario.
    if not nombre:
        raise ValidationError("El nombre del lote es obligatorio.")
    existentes = Lote.objects.filter(nombre__iexact=nombre)
    if lote_id is not None:
        existentes = existentes.exclude(pk=lote_id)
    if existentes.exists():
        raise ValidationError(f'Ya existe un lote con el nombre "{nombre}".')
    return validar_ambientes(ambientes)


def _guardar_ambientes(lote, ambientes):
    Ambiente.objects.bulk_create([
        Ambiente(lote=lote, tipo_suelo=suelo, rendimiento_esperado=rendimiento, superficie_ha=ha)
        for suelo, rendimiento, ha in ambientes
    ])


def crear_lote(actor, *, nombre, ambientes):
    require_editor(actor)
    nombre = nombre.strip()
    data = _validar_lote(nombre, ambientes)
    try:
        with transaction.atomic():
            lote = Lote.objects.create(
                codigo=_next_lote_codigo(), nombre=nombre,
                superficie_ha=sum(ha for _, _, ha in data),
                tipo_suelo=max(data, key=lambda item: item[2])[0],
                max_cultivos_principales=10, max_cultivos_secundarios=10,
                habilitado=True,
            )
            _guardar_ambientes(lote, data)
    except IntegrityError as exc:
        raise ValidationError(f'Ya existe un lote con el nombre "{nombre}".') from exc
    return lote


def actualizar_lote(actor, lote_id, *, nombre, ambientes, habilitado):
    require_editor(actor)
    lote = Lote.objects.get(pk=lote_id)
    nombre = nombre.strip()
    data = _validar_lote(nombre, ambientes, lote_id=lote.pk)
    with transaction.atomic():
        lote.nombre = nombre
        lote.habilitado = habilitado
        lote.superficie_ha = sum(ha for _, _, ha in data)
        lote.tipo_suelo = max(data, key=lambda item: item[2])[0]
        lote.save(update_fields=["nombre", "habilitado", "superficie_ha", "tipo_suelo"])
        lote.ambientes.all().delete()
        _guardar_ambientes(lote, data)
    return lote


def alternar_lote(actor, lote_id):
    require_editor(actor)
    lote = Lote.objects.get(pk=lote_id)
    lote.habilitado = not lote.habilitado
    lote.save(update_fields=["habilitado"])
    return lote
