"""Cálculos, consultas y edición de precios y costos."""

from dataclasses import dataclass
from typing import Dict, Tuple, Any

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q

from core.models import Campania, Costo, Cultivo, TipoCosto, TipoSuelo
from core.services.authorization import require_editor

# Componentes oficiales del costo de siembra desagregado
COMPONENTES_SIEMBRA = (
    "sc_seed",
    "sc_agro",
    "sc_fert",
    "sc_labor",
    "sc_structure",
)

COMPONENTES_SIEMBRA_SET = frozenset(COMPONENTES_SIEMBRA)


def calcular_costo_siembra(valores: Dict[str, float]) -> float:
    """Calcula el costo total de siembra (sc) sumando sus 5 componentes.

    Valores es un diccionario donde las claves pueden ser los códigos de los componentes
    ('sc_seed', 'sc_agro', 'sc_fert', 'sc_labor', 'sc_structure').
    """
    return sum(
        float(valores.get(code, 0.0) or 0.0)
        for code in COMPONENTES_SIEMBRA
    )


def calcular_sc_para_cultivo_campania(
    costos_lookup: Dict[Tuple[Any, str, Any, Any], float],
    cultivo_id: Any,
    campania_id: Any,
) -> float:
    """Calcula sc a partir de una lookup de costos con claves (cultivo_id, tipo_codigo, campania_id, lote_id)."""
    return sum(
        float(
            costos_lookup.get(
                (cultivo_id, code, campania_id, None),
                costos_lookup.get((cultivo_id, code, None, None), 0.0),
            )
            or 0.0
        )
        for code in COMPONENTES_SIEMBRA
    )


BARBECHO_COST_Q = Q(cultivo__codigo__icontains="BARBECHO") | Q(cultivo__nombre__icontains="BARBECHO")


@dataclass(frozen=True)
class ActualizacionCostos:
    modificados: int
    pendientes: int = 0
    cultivo_habilitado: Cultivo | None = None


def actualizar_costos(actor, valores, *, cultivo_id=None, habilitar=False):
    """Guarda valores y, si están revisados, habilita el cultivo seleccionado.

    Los costos válidos se guardan aunque queden revisiones pendientes.
    Un identificador inexistente se ignora, como en la edición HTML original.
    """
    require_editor(actor)
    updates = []
    for costo_id, raw_value in valores.items():
        try:
            value = float(raw_value)
            if value < 0:
                raise ValueError("negative")
            updates.append((int(costo_id), value))
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Los valores deben ser números mayores o iguales a cero."
            ) from exc

    with transaction.atomic():
        costos_by_id = Costo.objects.in_bulk([pk for pk, _ in updates])
        changed = 0
        for pk, value in updates:
            costo = costos_by_id.get(pk)
            if costo is None:
                continue
            if costo.valor != value:
                costo.valor = value
                changed += 1
            costo.configurado = True
            costo.save(update_fields=["valor", "configurado"])

        pendientes = 0
        cultivo_habilitado = None
        cultivo = obtener_cultivo(cultivo_id) if habilitar else None
        if cultivo is not None:
            pendientes = contar_costos_pendientes(cultivo)
            if not pendientes:
                cultivo.habilitado_optimizacion = True
                cultivo.save(update_fields=["habilitado_optimizacion"])
                cultivo_habilitado = cultivo
    return ActualizacionCostos(changed, pendientes, cultivo_habilitado)


def consultar_costos(*, selected_tipo="", selected_campania="", selected_cultivo="", selected_page="1", selected_arrendamiento_page="1"):
    costos = (
        Costo.objects.select_related("cultivo", "tipo_costo", "campania", "lote")
        .exclude(BARBECHO_COST_Q)
        .order_by(
            "tipo_costo__codigo",
            "cultivo__codigo",
            "campania__orden",
            "lote__codigo",
        )
    )

    if selected_tipo:
        costos = costos.filter(tipo_costo_id=selected_tipo)
    if selected_campania:
        costos = costos.filter(campania_id=selected_campania)
    if selected_cultivo:
        costos = costos.filter(cultivo_id=selected_cultivo)

    tipo_seleccionado_codigo = (
        TipoCosto.objects.filter(pk=selected_tipo)
        .values_list("codigo", flat=True)
        .first()
        if selected_tipo
        else None
    )
    show_costos_arrendamiento = tipo_seleccionado_codigo in {"frc", "vr"}
    show_costos_generales = not show_costos_arrendamiento
    costos_generales = costos.exclude(tipo_costo__codigo__in=("frc", "vr"))
    costos_arrendamiento = costos.filter(tipo_costo__codigo__in=("frc", "vr"))
    paginator = Paginator(costos_generales, 7)
    page_obj = paginator.get_page(selected_page)
    arrendamiento_paginator = Paginator(costos_arrendamiento, 7)
    arrendamiento_page_obj = arrendamiento_paginator.get_page(
        selected_arrendamiento_page
    )

    return {
        "page_obj": page_obj,
        "paginator": paginator,
        "arrendamiento_page_obj": arrendamiento_page_obj,
        "arrendamiento_paginator": arrendamiento_paginator,
        "show_costos_generales": show_costos_generales,
        "show_costos_arrendamiento": show_costos_arrendamiento,
        "tipo_seleccionado_codigo": tipo_seleccionado_codigo,
    }


def consultar_totales_siembra(*, tipo_seleccionado_codigo, selected_campania="", selected_cultivo=""):
    totales_siembra = []
    if tipo_seleccionado_codigo in (None, *COMPONENTES_SIEMBRA):
        componentes = (
            Costo.objects.filter(tipo_costo__codigo__in=COMPONENTES_SIEMBRA)
            .exclude(BARBECHO_COST_Q)
            .select_related("cultivo", "tipo_costo", "campania")
        )
        if selected_campania:
            componentes = componentes.filter(campania_id=selected_campania)
        if selected_cultivo:
            componentes = componentes.filter(cultivo_id=selected_cultivo)
        agrupados = {}
        for costo in componentes:
            if costo.campania is None:
                continue
            key = (costo.cultivo_id, costo.campania_id)
            grupo = agrupados.setdefault(
                key,
                {
                    "cultivo": costo.cultivo.codigo,
                    "campania": (
                        f"{costo.campania.fecha_inicio.year}/{costo.campania.fecha_inicio.year + 1}"
                        if costo.campania.fecha_inicio
                        else f"{2024 + costo.campania.orden}/{2025 + costo.campania.orden}"
                    ),
                    "valores": {},
                },
            )
            grupo["valores"][costo.tipo_costo.codigo] = costo.valor
        for key, grupo in agrupados.items():
            valores = grupo["valores"]
            grupo["grupo"] = f"{key[0]}-{key[1]}"
            grupo["sc_seed"] = valores.get("sc_seed", 0)
            grupo["sc_agro"] = valores.get("sc_agro", 0)
            grupo["sc_fert"] = valores.get("sc_fert", 0)
            grupo["sc_labor"] = valores.get("sc_labor", 0)
            grupo["sc_structure"] = valores.get("sc_structure", 0)
            grupo["total"] = calcular_costo_siembra(valores)
            totales_siembra.append(grupo)
        totales_siembra.sort(key=lambda item: (item["cultivo"], item["campania"]))

    return totales_siembra


def consultar_catalogos():
    return {
        "campanias": Campania.objects.order_by("orden"),
        "tipos_costo": TipoCosto.objects.order_by("codigo"),
        "cultivos": Cultivo.objects.exclude(
            Q(codigo__icontains="BARBECHO") | Q(nombre__icontains="BARBECHO")
        ).order_by("codigo"),
        "suelos": TipoSuelo.objects.order_by("codigo"),
    }


def obtener_cultivo(cultivo_id):
    return Cultivo.objects.filter(pk=cultivo_id).first() if cultivo_id else None


def contar_costos_pendientes(cultivo):
    return cultivo.costo_set.filter(configurado=False).count() if cultivo else 0


def anio_base_costos():
    return (Campania.objects.order_by("orden")
            .values_list("fecha_inicio__year", flat=True).first() or 2025)
