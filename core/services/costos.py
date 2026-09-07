"""Servicio de cálculo y constantes para los componentes del costo de siembra."""

from typing import Dict, Iterable, Tuple, Any

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
