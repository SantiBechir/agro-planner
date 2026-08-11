"""Analytical indicators derived from the database without changing the solver."""

from collections import defaultdict

from django.db.models import Q

from core.models import Campania, CompatibilidadCultivoSuelo, Costo, Cultivo, Lote


# Same productivity scenarios used by Plan. agrícola_v5.py.  They are only
# applied to analytical displays; they do not modify optimization inputs.
PRODUCTIVITY_LEVELS = {"A": 1.2, "M": 1.0, "B": 0.8}


def build_economic_indicators():
    """Return margins and break-even yields from the current database inputs.

    This mirrors the current solver's revenue and cost equations.  It never
    instantiates or changes the Pyomo model, the database, or Excel inputs.
    """
    barbecho_q = Q(codigo__iexact="BARBECHO") | Q(nombre__iexact="BARBECHO")
    cultivos = list(Cultivo.objects.exclude(barbecho_q).order_by("codigo"))
    campanias = list(Campania.objects.order_by("orden"))

    values = _cost_values(cultivos)
    rental_by_crop_campaign = _average_rental_per_hectare(cultivos, campanias)
    yield_by_crop_soil = {
        (rendimiento.cultivo_id, rendimiento.tipo_suelo_id): rendimiento.valor
        for cultivo in cultivos
        for rendimiento in cultivo.rendimientocultivosuelo_set.select_related(
            "tipo_suelo"
        )
    }
    soils_by_crop = defaultdict(list)
    for compatibility in CompatibilidadCultivoSuelo.objects.filter(
        cultivo__in=cultivos, compatible=True
    ).select_related("tipo_suelo"):
        soils_by_crop[compatibility.cultivo_id].append(compatibility.tipo_suelo)

    margins = []
    break_even = []
    for cultivo in cultivos:
        for campania in campanias:
            inputs = _inputs_for(cultivo.id, campania.id, values)
            for suelo in soils_by_crop[cultivo.id]:
                base_yield = yield_by_crop_soil.get((cultivo.id, suelo.id))
                if base_yield is None:
                    continue
                for level, factor in PRODUCTIVITY_LEVELS.items():
                    yield_ton_ha = base_yield * factor
                    row = _margin_row(
                        cultivo,
                        campania,
                        suelo,
                        level,
                        yield_ton_ha,
                        inputs,
                        rental_by_crop_campaign[(cultivo.id, campania.id)],
                    )
                    margins.append(row)
                    break_even.append(
                        {
                            "cultivo": cultivo.codigo,
                            "cultivo_id": cultivo.id,
                            "campania": _campania_label(campania),
                            "campania_id": campania.id,
                            "suelo": suelo.nombre,
                            "suelo_id": suelo.id,
                            "nivel": level,
                            "rendimiento_estimado": yield_ton_ha,
                            "rendimiento_indiferencia": row["rendimiento_indiferencia"],
                            "precio_neto": row["precio_neto"],
                        }
                    )
    return {"margins": margins, "break_even": break_even}


def _cost_values(cultivos):
    values = {}
    for costo in Costo.objects.filter(cultivo__in=cultivos).select_related(
        "tipo_costo"
    ):
        values[(costo.cultivo_id, costo.tipo_costo.codigo, costo.campania_id, costo.lote_id)] = costo.valor
    return values


def _campania_label(campania):
    inicio = 2024 + campania.orden
    return f"{inicio}/{inicio + 1}"


def _inputs_for(cultivo_id, campania_id, values):
    def value(code):
        return values.get(
            (cultivo_id, code, campania_id, None),
            values.get((cultivo_id, code, None, None), 0.0),
        )

    return {code: value(code) for code in ("fsp", "sc", "hc", "tf", "scp", "cp", "st", "cst", "clt")}


def _average_rental_per_hectare(cultivos, campanias):
    """Weighted rental inputs per ha, using the solver's fixed/variable inputs."""
    result = defaultdict(lambda: (0.0, 0.0))
    lots = list(Lote.objects.select_related("tipo_suelo"))
    costs = _cost_values(cultivos)

    compatible = {
        (item.cultivo_id, item.tipo_suelo_id)
        for item in CompatibilidadCultivoSuelo.objects.filter(
            cultivo__in=cultivos, compatible=True
        )
    }
    for cultivo in cultivos:
        for campania in campanias:
            inputs = _inputs_for(cultivo.id, campania.id, costs)
            total_area = total_fixed = total_variable_rate = 0.0
            for lote in lots:
                if (cultivo.id, lote.tipo_suelo_id) not in compatible:
                    continue
                fixed = costs.get((cultivo.id, "frc", campania.id, lote.id), 0.0)
                variable_rate = costs.get(
                    (cultivo.id, "vr", campania.id, lote.id), 0.0
                )
                total_fixed += fixed
                total_variable_rate += variable_rate * lote.superficie_ha
                total_area += lote.superficie_ha
            result[(cultivo.id, campania.id)] = (
                (
                    total_fixed / total_area,
                    total_variable_rate / total_area,
                )
                if total_area
                else (0.0, 0.0)
            )
    return result


def _margin_row(cultivo, campania, suelo, level, yield_ton_ha, inputs, rental):
    fixed_rent, variable_rent_rate = rental
    price = inputs["fsp"]
    cultivation = inputs["sc"]
    harvest = inputs["hc"]
    commercial = inputs["tf"] * price * yield_ton_ha
    conditioning = inputs["scp"] * inputs["cp"] * yield_ton_ha
    transport = (
        inputs["st"] * inputs["cst"] + (1 - inputs["st"]) * inputs["clt"]
    ) * yield_ton_ha
    gross_income = price * yield_ton_ha
    direct_costs = cultivation + harvest + commercial + conditioning + transport
    variable_rent = price * variable_rent_rate * yield_ton_ha
    price_net = price * (1 - inputs["tf"]) - inputs["scp"] * inputs["cp"] - (
        inputs["st"] * inputs["cst"] + (1 - inputs["st"]) * inputs["clt"]
    )
    break_even = (cultivation + harvest) / price_net if price_net > 0 else None

    return {
        "cultivo": cultivo.codigo,
        "cultivo_id": cultivo.id,
        "campania": _campania_label(campania),
        "campania_id": campania.id,
        "suelo": suelo.nombre,
        "suelo_id": suelo.id,
        "nivel": level,
        "rendimiento": yield_ton_ha,
        "ingreso_bruto": gross_income,
        "costo_cultivo": cultivation,
        "costo_cosecha": harvest,
        "costo_comercializacion": commercial,
        "costo_acondicionamiento": conditioning,
        "costo_flete": transport,
        "costo_arrendamiento_fijo": fixed_rent,
        "costo_arrendamiento_variable": variable_rent,
        "costos_directos": direct_costs,
        "margen_bruto": gross_income - direct_costs,
        "margen_con_arrendamiento": gross_income - direct_costs - fixed_rent - variable_rent,
        "precio_neto": price_net,
        "rendimiento_indiferencia": break_even,
    }
