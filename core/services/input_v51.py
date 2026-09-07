"""Lectura, validación y persistencia del snapshot Input v5.1."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import math
import unicodedata

import pandas as pd

from core.models import (
    Ambiente,
    Campania,
    CampaniaHistorica,
    CompatibilidadCultivoSuelo,
    Costo,
    Cultivo,
    HistorialLoteCultivo,
    ImpactoRotacion,
    LimiteSuperficieCultivoCampania,
    Lote,
    NivelAntiguedad,
    RendimientoCultivoSuelo,
    SecuenciaPermitida,
    SetupCultivo,
    SlotSiembra,
    TipoCosto,
    TipoSuelo,
)
from core.services.costos import COMPONENTES_SIEMBRA, calcular_costo_siembra


REQUIRED_SHEETS = {
    "Sets",
    "Plots (J)",
    "Costs",
    "Crops (I)",
    "History (Ch)",
    "Yields",
    "Rotations(red)",
    "Fechas",
}

SOIL_NAMES = {"S1": "Molisol", "S2": "Alfisol", "S3": "Vertisol"}

COST_TYPES = (
    ("fsp", "Future selling price", "USD/ton", False),
    ("sc_seed", "Seed cost", "USD/ha", False),
    ("sc_agro", "Agrochemical cost", "USD/ha", False),
    ("sc_fert", "Fertilizer cost", "USD/ha", False),
    ("sc_labor", "Labor cost", "USD/ha", False),
    ("sc_structure", "Structure cost", "USD/ha", False),
    ("hc", "Harvesting cost", "USD/ha", False),
    ("frc", "Fixed rental cost", "USD/ha", False),
    ("vr", "Variable rental cost", "%", True),
    ("tf", "Trading fee", "%", True),
    ("scp", "Share conditioned production", "%", True),
    ("cp", "Conditioning cost", "USD/ton", False),
    ("st", "Short transport/bagging share", "%", True),
    ("cst", "Short-haul transport cost", "USD/ton", False),
    ("clt", "Long-haul transport cost", "USD/ton", False),
)


class InputValidationError(ValueError):
    """Error de estructura o contenido del Excel, antes de persistir."""


@dataclass
class InputV51Data:
    lotes: list[str]
    cultivos: list[str]
    cultivos_no_secuenciales: set[str]
    cultivos_principales: set[str]
    cultivos_secundarios: set[str]
    suelos: list[str]
    campanias: list[str]
    slots: list[str]
    campanias_historicas: list[str]
    niveles: list[str]
    fecha_base: date
    parametros_cultivo: dict[str, dict]
    parametros_lote: dict[str, dict]
    proporciones: dict[tuple[str, str], float]
    productividades: dict[tuple[str, str], str]
    limites: dict[tuple[str, str], tuple[float, float]]
    costos: dict[tuple[str, str, str | None, str | None], float]
    setups: dict[tuple[str, str], int]
    secuencias: dict[tuple[str, str], bool]
    compatibilidades: dict[tuple[str, str], bool]
    historial: dict[tuple[str, str, str], bool]
    alfas: dict[str, float]
    rendimientos: dict[tuple[str, str], float]
    rotaciones: dict[tuple[str, str], float]


@dataclass
class ImportStats:
    created: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    updated: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    unchanged: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    disabled: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    deleted: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def lines(self):
        names = sorted(
            set(self.created)
            | set(self.updated)
            | set(self.unchanged)
            | set(self.disabled)
            | set(self.deleted)
        )
        return [
            f"  {name}: {self.created[name]} creados, "
            f"{self.updated[name]} actualizados, {self.unchanged[name]} sin cambios, "
            f"{self.disabled[name]} deshabilitados, {self.deleted[name]} eliminados"
            for name in names
        ]


def _norm(value) -> str:
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value).strip())
    return " ".join(
        "".join(char for char in text if not unicodedata.combining(char))
        .lower()
        .split()
    )


def _code(value) -> str:
    return str(value).strip().upper()


def _number(value, context: str) -> float:
    if pd.isna(value) or isinstance(value, bool):
        raise InputValidationError(f"{context}: falta un valor numérico calculado.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{context}: '{value}' no es numérico.") from exc
    if not math.isfinite(result):
        raise InputValidationError(f"{context}: el valor debe ser finito.")
    return result


def _integer(value, context: str) -> int:
    result = _number(value, context)
    if not result.is_integer():
        raise InputValidationError(f"{context}: se esperaba un número entero.")
    return int(result)


def _find_title(df, sheet: str, *needles: str) -> tuple[int, int]:
    normalized_needles = tuple(_norm(needle) for needle in needles)
    for row in range(df.shape[0]):
        for col in range(df.shape[1]):
            value = _norm(df.iat[row, col])
            if value and all(needle in value for needle in normalized_needles):
                return row, col
    raise InputValidationError(
        f"{sheet}: no se encontró la sección '{' / '.join(needles)}'."
    )


def _find_header_sequence(
    df, sheet: str, title_row: int, expected: list[str], *, start_col: int = 0
) -> tuple[int, int]:
    expected_norm = [_norm(value) for value in expected]
    for row in range(title_row, min(title_row + 5, df.shape[0])):
        current = [_norm(value) for value in df.iloc[row].tolist()]
        width = len(expected_norm)
        for col in range(start_col, len(current) - width + 1):
            if current[col : col + width] == expected_norm:
                return row, col
    raise InputValidationError(
        f"{sheet}: no se encontraron los encabezados {expected}."
    )


def _matrix(
    df,
    sheet: str,
    title: tuple[str, ...],
    rows: list[str],
    columns: list[str],
    *,
    value_kind: str = "number",
):
    title_row, title_col = _find_title(df, sheet, *title)
    header_row, first_value_col = _find_header_sequence(
        df, sheet, title_row, columns, start_col=title_col
    )
    expected_rows = set(rows)
    key_col = None
    for candidate in range(first_value_col - 1, -1, -1):
        found = {
            _code(value)
            for value in df.iloc[header_row + 1 :, candidate].tolist()
            if pd.notna(value) and _code(value) in expected_rows
        }
        if found == expected_rows:
            key_col = candidate
            break
    if key_col is None:
        raise InputValidationError(f"{sheet}: la matriz '{title[0]}' no tiene clave.")
    result = {}
    for row_number in range(header_row + 1, df.shape[0]):
        key = _code(df.iat[row_number, key_col]) if pd.notna(df.iat[row_number, key_col]) else ""
        if key not in expected_rows:
            continue
        if key in result:
            raise InputValidationError(f"{sheet}: identificador duplicado '{key}'.")
        values = {}
        for offset, column in enumerate(columns):
            context = f"{sheet}/{title[0]}/{key}/{column}"
            raw = df.iat[row_number, first_value_col + offset]
            if value_kind == "productivity":
                value = _code(raw)
                if value not in {"A", "M", "B"}:
                    raise InputValidationError(
                        f"{context}: productividad inválida '{raw}', use A, M o B."
                    )
            elif value_kind == "integer":
                value = _integer(raw, context)
            elif value_kind == "binary":
                value = _integer(raw, context)
                if value not in {0, 1}:
                    raise InputValidationError(f"{context}: se esperaba 0 o 1.")
            else:
                value = _number(raw, context)
            values[column] = value
        result[key] = values
    missing = [key for key in rows if key not in result]
    if missing:
        raise InputValidationError(
            f"{sheet}/{title[0]}: faltan filas para {', '.join(missing)}."
        )
    return result


def _paired_matrix(
    df,
    sheet: str,
    title: tuple[str, ...],
    first_keys: list[str],
    second_keys: list[str],
    columns: list[str],
    *,
    value_kind: str = "number",
):
    title_row, title_col = _find_title(df, sheet, *title)
    header_row, first_value_col = _find_header_sequence(
        df, sheet, title_row, columns, start_col=title_col
    )
    if first_value_col < 2:
        raise InputValidationError(f"{sheet}: la matriz '{title[0]}' no tiene dos claves.")
    expected_first = set(first_keys)
    expected_second = set(second_keys)
    result = {}
    for row_number in range(header_row + 1, df.shape[0]):
        first = _code(df.iat[row_number, first_value_col - 2]) if pd.notna(df.iat[row_number, first_value_col - 2]) else ""
        second = _code(df.iat[row_number, first_value_col - 1]) if pd.notna(df.iat[row_number, first_value_col - 1]) else ""
        if first not in expected_first or second not in expected_second:
            continue
        key = (first, second)
        if key in result:
            raise InputValidationError(f"{sheet}: combinación duplicada {first}/{second}.")
        values = {}
        for offset, column in enumerate(columns):
            context = f"{sheet}/{title[0]}/{first}/{second}/{column}"
            raw = df.iat[row_number, first_value_col + offset]
            value = _number(raw, context)
            if value_kind == "percentage" and not 0 <= value <= 1:
                raise InputValidationError(
                    f"{context}: el porcentaje debe estar entre 0 y 1."
                )
            values[column] = value
        result[key] = values
    expected = {(first, second) for first in first_keys for second in second_keys}
    missing = expected - set(result)
    if missing:
        sample = ", ".join(f"{a}/{b}" for a, b in sorted(missing)[:8])
        raise InputValidationError(
            f"{sheet}/{title[0]}: faltan combinaciones ({sample})."
        )
    return result


def _vector(df, sheet: str, title: tuple[str, ...], keys: list[str], *, percentage=False):
    title_row, value_col = _find_title(df, sheet, *title)
    key_col = value_col - 1
    if key_col < 0:
        raise InputValidationError(f"{sheet}: la sección '{title[0]}' no tiene clave.")
    expected = set(keys)
    result = {}
    for row_number in range(title_row + 1, df.shape[0]):
        key = _code(df.iat[row_number, key_col]) if pd.notna(df.iat[row_number, key_col]) else ""
        if key not in expected:
            continue
        if key in result:
            raise InputValidationError(f"{sheet}/{title[0]}: clave duplicada '{key}'.")
        value = _number(df.iat[row_number, value_col], f"{sheet}/{title[0]}/{key}")
        if percentage and not 0 <= value <= 1:
            raise InputValidationError(
                f"{sheet}/{title[0]}/{key}: el porcentaje debe estar entre 0 y 1."
            )
        result[key] = value
    missing = [key for key in keys if key not in result]
    if missing:
        raise InputValidationError(
            f"{sheet}/{title[0]}: faltan valores para {', '.join(missing)}."
        )
    return result


def _set_column(df, header: str, *, required=True) -> list[str]:
    normalized = [_norm(value) for value in df.iloc[0].tolist()]
    try:
        col = normalized.index(_norm(header))
    except ValueError as exc:
        if not required:
            return []
        raise InputValidationError(f"Sets: falta el encabezado '{header}'.") from exc
    values = [_code(value) for value in df.iloc[1:, col].tolist() if pd.notna(value)]
    if len(values) != len(set(values)):
        raise InputValidationError(f"Sets/{header}: hay identificadores duplicados.")
    if required and not values:
        raise InputValidationError(f"Sets/{header}: el conjunto está vacío.")
    return values


def read_and_validate_input_v51(path: str | Path) -> InputV51Data:
    """Lee todo el libro a memoria y valida referencias antes de cualquier escritura."""
    path = Path(path)
    if not path.is_file():
        raise InputValidationError(f"No se encontró el archivo: {path}")
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:
        raise InputValidationError(f"No se pudo abrir el Excel: {exc}") from exc
    missing_sheets = sorted(REQUIRED_SHEETS - set(xl.sheet_names))
    if missing_sheets:
        raise InputValidationError(
            f"Faltan hojas obligatorias: {', '.join(missing_sheets)}."
        )
    sheets = {
        name: pd.read_excel(xl, sheet_name=name, header=None)
        for name in REQUIRED_SHEETS
    }

    sets = sheets["Sets"]
    lotes = _set_column(sets, "J")
    cultivos = _set_column(sets, "I")
    no_secuenciales = set(_set_column(sets, "I_NOSEC"))
    principales = set(_set_column(sets, "I_P"))
    secundarios = set(_set_column(sets, "I_S"))
    suelos = _set_column(sets, "S")
    campanias = _set_column(sets, "C")
    slots = _set_column(sets, "T")
    historicas = _set_column(sets, "C_H")
    niveles = _set_column(sets, "L")

    for label, subset, parent in (
        ("I_NOSEC", no_secuenciales, set(cultivos)),
        ("I_P", principales, set(cultivos)),
        ("I_S", secundarios, set(cultivos)),
    ):
        unknown = sorted(subset - parent)
        if unknown:
            raise InputValidationError(
                f"Sets/{label}: referencias a cultivos inexistentes: {', '.join(unknown)}."
            )
    if principales & secundarios:
        raise InputValidationError("Sets: un cultivo no puede ser principal y secundario.")
    if len(slots) % len(campanias):
        raise InputValidationError("Sets: los slots no se pueden distribuir entre campañas.")

    fechas = sheets["Fechas"]
    fecha_raw = fechas.iat[0, 0]
    if isinstance(fecha_raw, pd.Timestamp):
        fecha_base = fecha_raw.date()
    elif isinstance(fecha_raw, datetime):
        fecha_base = fecha_raw.date()
    elif isinstance(fecha_raw, date):
        fecha_base = fecha_raw
    else:
        raise InputValidationError("Fechas/A1: se esperaba la fecha base de la planificación.")

    crops = sheets["Crops (I)"]
    crop_headers = [_norm(value) for value in crops.iloc[0].tolist()]
    try:
        parameter_cols = {name: crop_headers.index(_norm(name)) for name in ("I", "gt", "st_start", "st_end")}
    except ValueError as exc:
        raise InputValidationError("Crops (I): faltan encabezados I, gt, st_start o st_end.") from exc
    parametros_cultivo = {}
    for row_number in range(1, crops.shape[0]):
        raw_code = crops.iat[row_number, parameter_cols["I"]]
        code = _code(raw_code) if pd.notna(raw_code) else ""
        if code not in set(cultivos):
            continue
        if code in parametros_cultivo:
            raise InputValidationError(f"Crops (I): cultivo duplicado '{code}'.")
        parametros_cultivo[code] = {
            "duracion_dias": _integer(crops.iat[row_number, parameter_cols["gt"]], f"Crops (I)/{code}/gt"),
            "siembra_inicio": _integer(crops.iat[row_number, parameter_cols["st_start"]], f"Crops (I)/{code}/st_start"),
            "siembra_fin": _integer(crops.iat[row_number, parameter_cols["st_end"]], f"Crops (I)/{code}/st_end"),
        }
    missing_crops = set(cultivos) - set(parametros_cultivo)
    if missing_crops:
        raise InputValidationError(f"Crops (I): faltan parámetros para {', '.join(sorted(missing_crops))}.")

    setups_raw = _matrix(crops, "Crops (I)", ("setup",), cultivos, cultivos, value_kind="integer")
    sequences_raw = _matrix(crops, "Crops (I)", ("ar", "secuenciamiento"), cultivos, cultivos, value_kind="binary")
    compatibility_raw = _matrix(crops, "Crops (I)", ("compatibilidad", "suelo"), cultivos, suelos, value_kind="binary")

    plots = sheets["Plots (J)"]
    plot_headers = [_norm(value) for value in plots.iloc[0].tolist()]
    try:
        plot_cols = {name: plot_headers.index(_norm(name)) for name in ("J", "ha", "max_m", "max_s")}
    except ValueError as exc:
        raise InputValidationError("Plots (J): faltan encabezados J, ha, max_m o max_s.") from exc
    parametros_lote = {}
    for row_number in range(1, plots.shape[0]):
        raw_code = plots.iat[row_number, plot_cols["J"]]
        code = _code(raw_code) if pd.notna(raw_code) else ""
        if code not in set(lotes):
            continue
        superficie = _number(plots.iat[row_number, plot_cols["ha"]], f"Plots (J)/{code}/ha")
        if superficie <= 0:
            raise InputValidationError(f"Plots (J)/{code}/ha: la superficie debe ser positiva.")
        parametros_lote[code] = {
            "superficie_ha": superficie,
            "max_cultivos_principales": _integer(plots.iat[row_number, plot_cols["max_m"]], f"Plots (J)/{code}/max_m"),
            "max_cultivos_secundarios": _integer(plots.iat[row_number, plot_cols["max_s"]], f"Plots (J)/{code}/max_s"),
        }
    if set(parametros_lote) != set(lotes):
        raise InputValidationError("Plots (J): faltan o se repiten lotes del conjunto J.")

    proportions_raw = _matrix(plots, "Plots (J)", ("proporcion", "suelo"), lotes, suelos)
    productivity_raw = _matrix(plots, "Plots (J)", ("rendimiento", "lote"), lotes, suelos, value_kind="productivity")
    max_limits = _matrix(plots, "Plots (J)", ("limite max",), cultivos, campanias)
    min_limits = _matrix(plots, "Plots (J)", ("limite min",), cultivos, campanias)
    proporciones = {}
    productividades = {}
    for lote in lotes:
        total = 0.0
        for suelo in suelos:
            value = proportions_raw[lote][suelo]
            if not 0 <= value <= 1:
                raise InputValidationError(f"Plots (J)/proporción/{lote}/{suelo}: debe estar entre 0 y 1.")
            total += value
            proporciones[(lote, suelo)] = value
            productividades[(lote, suelo)] = productivity_raw[lote][suelo]
        if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-6):
            raise InputValidationError(f"Plots (J)/{lote}: las proporciones suman {total}, no 1.")
    limites = {}
    for cultivo in cultivos:
        for campania in campanias:
            minimum = min_limits[cultivo][campania]
            maximum = max_limits[cultivo][campania]
            if minimum < 0 or maximum < 0 or minimum > maximum:
                raise InputValidationError(
                    f"Plots (J)/límites/{cultivo}/{campania}: mínimo={minimum}, máximo={maximum}."
                )
            limites[(cultivo, campania)] = (minimum, maximum)

    costs = sheets["Costs"]
    cost_matrices = {
        "fsp": _matrix(costs, "Costs", ("precio de venta", "fsp"), cultivos, campanias),
        "sc_seed": _matrix(costs, "Costs", ("costo de semilla",), cultivos, campanias),
        "sc_agro": _matrix(costs, "Costs", ("costo de agro",), cultivos, campanias),
        "sc_fert": _matrix(costs, "Costs", ("costo de fertilizantes",), cultivos, campanias),
        "sc_labor": _matrix(costs, "Costs", ("costo de labores",), cultivos, campanias),
        "sc_structure": _matrix(costs, "Costs", ("costo de estructura",), cultivos, campanias),
        "hc": _matrix(costs, "Costs", ("costo de cosecha", "hc"), cultivos, campanias),
        "cp": _matrix(costs, "Costs", ("costo de acondicionamiento", "cp"), cultivos, campanias),
        "cst": _matrix(costs, "Costs", ("costo del flete corto", "cst"), cultivos, campanias),
        "clt": _matrix(costs, "Costs", ("costo de flete largo", "clt"), cultivos, campanias),
    }
    aggregate_sc = _matrix(costs, "Costs", ("costo de siembra", "sc"), cultivos, campanias)
    fixed_rent = _paired_matrix(costs, "Costs", ("arrendamiento fijo", "frc"), cultivos, lotes, campanias)
    variable_rent = _paired_matrix(costs, "Costs", ("arrendamiento variable", "vr"), cultivos, lotes, campanias, value_kind="percentage")
    vectors = {
        "tf": _vector(costs, "Costs", ("tarifa", "tf"), cultivos, percentage=True),
        "scp": _vector(costs, "Costs", ("produccion", "acondicionar", "scp"), cultivos, percentage=True),
        "st": _vector(costs, "Costs", ("proporcion", "flete corto", "st"), cultivos, percentage=True),
    }
    costos = {}
    for code, matrix in cost_matrices.items():
        for cultivo in cultivos:
            for campania in campanias:
                value = matrix[cultivo][campania]
                if value < 0:
                    raise InputValidationError(f"Costs/{code}/{cultivo}/{campania}: no puede ser negativo.")
                costos[(code, cultivo, campania, None)] = value
    for cultivo in cultivos:
        for campania in campanias:
            component_values = {
                code: cost_matrices[code][cultivo][campania]
                for code in COMPONENTES_SIEMBRA
            }
            derived = calcular_costo_siembra(component_values)
            informed = aggregate_sc[cultivo][campania]
            if not math.isclose(derived, informed, rel_tol=0, abs_tol=1e-6):
                raise InputValidationError(
                    f"Costs/sc/{cultivo}/{campania}: total {informed} distinto de la suma {derived}."
                )
    for (cultivo, lote), values in fixed_rent.items():
        for campania, value in values.items():
            if value < 0:
                raise InputValidationError(f"Costs/frc/{cultivo}/{lote}/{campania}: no puede ser negativo.")
            costos[("frc", cultivo, campania, lote)] = value
    for (cultivo, lote), values in variable_rent.items():
        for campania, value in values.items():
            costos[("vr", cultivo, campania, lote)] = value
    for code, values in vectors.items():
        for cultivo, value in values.items():
            costos[(code, cultivo, None, None)] = value

    history_sheet = sheets["History (Ch)"]
    history_raw = _paired_matrix(history_sheet, "History (Ch)", ("crop history", "xh"), cultivos, lotes, historicas, value_kind="number")
    alpha_values = _vector(history_sheet, "History (Ch)", ("α",), niveles)
    historial = {}
    for (cultivo, lote), values in history_raw.items():
        for historical, value in values.items():
            if value not in {0, 1}:
                raise InputValidationError(f"History (Ch)/{cultivo}/{lote}/{historical}: se esperaba 0 o 1.")
            historial[(cultivo, lote, historical)] = bool(value)

    yields = _matrix(sheets["Yields"], "Yields", ("yield_max",), suelos, cultivos)
    rotations = _matrix(sheets["Rotations(red)"], "Rotations(red)", ("cultivo predecesor",), cultivos, cultivos)

    return InputV51Data(
        lotes=lotes,
        cultivos=cultivos,
        cultivos_no_secuenciales=no_secuenciales,
        cultivos_principales=principales,
        cultivos_secundarios=secundarios,
        suelos=suelos,
        campanias=campanias,
        slots=slots,
        campanias_historicas=historicas,
        niveles=niveles,
        fecha_base=fecha_base,
        parametros_cultivo=parametros_cultivo,
        parametros_lote=parametros_lote,
        proporciones=proporciones,
        productividades=productividades,
        limites=limites,
        costos=costos,
        setups={(a, b): setups_raw[a][b] for a in cultivos for b in cultivos},
        secuencias={(a, b): bool(sequences_raw[a][b]) for a in cultivos for b in cultivos},
        compatibilidades={(a, s): bool(compatibility_raw[a][s]) for a in cultivos for s in suelos},
        historial=historial,
        alfas=alpha_values,
        rendimientos={(s, c): yields[s][c] for s in suelos for c in cultivos},
        rotaciones={(a, b): rotations[a][b] for a in cultivos for b in cultivos},
    )


def _same(current, desired):
    if isinstance(current, float) or isinstance(desired, float):
        try:
            return math.isclose(float(current), float(desired), rel_tol=0, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return current == desired


def _upsert(model, lookup, defaults, stats: ImportStats, label: str):
    obj, created = model.objects.get_or_create(**lookup, defaults=defaults)
    if created:
        stats.created[label] += 1
        return obj
    changed = [field for field, value in defaults.items() if not _same(getattr(obj, field), value)]
    if changed:
        for field in changed:
            setattr(obj, field, defaults[field])
        obj.save(update_fields=changed)
        stats.updated[label] += 1
    else:
        stats.unchanged[label] += 1
    return obj


def _delete_queryset(queryset, stats: ImportStats, label: str):
    count = queryset.count()
    if count:
        queryset.delete()
        stats.deleted[label] += count


def persist_input_v51(data: InputV51Data) -> ImportStats:
    """Reconcilia la base con el snapshot. Debe invocarse dentro de atomic()."""
    stats = ImportStats()
    soils = {
        code: _upsert(TipoSuelo, {"codigo": code}, {"nombre": SOIL_NAMES.get(code, code)}, stats, "TipoSuelo")
        for code in data.suelos
    }
    campaigns = {}
    for index, code in enumerate(data.campanias):
        start_year = data.fecha_base.year + index
        campaigns[code] = _upsert(
            Campania,
            {"codigo": code},
            {"orden": index + 1, "fecha_inicio": date(start_year, 6, 1), "fecha_fin": date(start_year + 1, 5, 31)},
            stats,
            "Campania",
        )
    slots_per_campaign = len(data.slots) // len(data.campanias)
    for index, code in enumerate(data.slots):
        campaign = campaigns[data.campanias[index // slots_per_campaign]]
        _upsert(SlotSiembra, {"codigo": code}, {"orden": index + 1, "campania": campaign}, stats, "SlotSiembra")

    for index, code in enumerate(data.niveles):
        _upsert(NivelAntiguedad, {"codigo": code}, {"orden": index + 1, "lag": index, "alfa": data.alfas[code]}, stats, "NivelAntiguedad")

    crops = {}
    for code in data.cultivos:
        params = data.parametros_cultivo[code]
        crop_type = Cultivo.Tipo.PRINCIPAL if code in data.cultivos_principales else Cultivo.Tipo.SECUNDARIO if code in data.cultivos_secundarios else Cultivo.Tipo.OTRO
        crops[code] = _upsert(
            Cultivo,
            {"codigo": code},
            {"nombre": code, "tipo": crop_type, **params, "no_repetir_sin_intermedio": code in data.cultivos_no_secuenciales, "habilitado_optimizacion": True},
            stats,
            "Cultivo",
        )
    disabled_crops = Cultivo.objects.exclude(codigo__in=data.cultivos).filter(habilitado_optimizacion=True).update(habilitado_optimizacion=False)
    stats.disabled["Cultivo"] += disabled_crops

    lots = {}
    for code in data.lotes:
        params = data.parametros_lote[code]
        dominant = max(data.suelos, key=lambda soil: data.proporciones[(code, soil)])
        lots[code] = _upsert(
            Lote,
            {"codigo": code},
            {"nombre": code, **params, "tipo_suelo": soils[dominant], "habilitado": True},
            stats,
            "Lote",
        )
        imported_soils = []
        for soil_code in data.suelos:
            proportion = data.proporciones[(code, soil_code)]
            if proportion <= 0:
                continue
            imported_soils.append(soils[soil_code].pk)
            _upsert(
                Ambiente,
                {"lote": lots[code], "tipo_suelo": soils[soil_code]},
                {"superficie_ha": params["superficie_ha"] * proportion, "rendimiento_esperado": data.productividades[(code, soil_code)]},
                stats,
                "Ambiente",
            )
        _delete_queryset(lots[code].ambientes.exclude(tipo_suelo_id__in=imported_soils), stats, "Ambiente")
    disabled_lots = Lote.objects.exclude(codigo__in=data.lotes).filter(habilitado=True).update(habilitado=False)
    stats.disabled["Lote"] += disabled_lots

    historical = {}
    for code in data.campanias_historicas:
        lag = int(code.removeprefix("CH"))
        year = data.fecha_base.year - lag
        obj = CampaniaHistorica.objects.filter(codigo=code).first()
        if obj:
            if obj.anio_inicio != year:
                conflict = CampaniaHistorica.objects.filter(anio_inicio=year).exclude(pk=obj.pk).first()
                if conflict:
                    conflict.codigo = f"CH_{conflict.anio_inicio}_{conflict.pk}"
                    conflict.save(update_fields=["codigo"])
                obj.anio_inicio = year
                obj.save(update_fields=["anio_inicio"])
                stats.updated["CampaniaHistorica"] += 1
            else:
                stats.unchanged["CampaniaHistorica"] += 1
            historical[code] = obj
        else:
            obj_with_year = CampaniaHistorica.objects.filter(anio_inicio=year).first()
            if obj_with_year:
                obj_with_year.codigo = code
                obj_with_year.save(update_fields=["codigo"])
                stats.updated["CampaniaHistorica"] += 1
                historical[code] = obj_with_year
            else:
                historical[code] = CampaniaHistorica.objects.create(codigo=code, anio_inicio=year)
                stats.created["CampaniaHistorica"] += 1

    cost_types = {}
    for code, description, unit, percentage in COST_TYPES:
        cost_types[code] = _upsert(TipoCosto, {"codigo": code}, {"descripcion": description, "unidad": unit, "es_porcentual": percentage}, stats, "TipoCosto")
    _delete_queryset(Costo.objects.filter(tipo_costo__codigo="sc"), stats, "Costo")
    _delete_queryset(TipoCosto.objects.filter(codigo="sc"), stats, "TipoCosto")

    desired_cost_ids = []
    for (type_code, crop_code, campaign_code, lot_code), value in data.costos.items():
        lookup = {
            "tipo_costo": cost_types[type_code],
            "cultivo": crops[crop_code],
            "campania": campaigns[campaign_code] if campaign_code else None,
            "lote": lots[lot_code] if lot_code else None,
        }
        cost = _upsert(Costo, lookup, {"valor": value, "configurado": True}, stats, "Costo")
        desired_cost_ids.append(cost.pk)
    _delete_queryset(
        Costo.objects.filter(tipo_costo__codigo__in=[item[0] for item in COST_TYPES]).exclude(pk__in=desired_cost_ids),
        stats,
        "Costo",
    )

    desired_limit_ids = []
    for (crop_code, campaign_code), (minimum, maximum) in data.limites.items():
        obj = _upsert(LimiteSuperficieCultivoCampania, {"cultivo": crops[crop_code], "campania": campaigns[campaign_code]}, {"min_ha": minimum, "max_ha": maximum}, stats, "LimiteSuperficieCultivoCampania")
        desired_limit_ids.append(obj.pk)
    _delete_queryset(LimiteSuperficieCultivoCampania.objects.exclude(pk__in=desired_limit_ids), stats, "LimiteSuperficieCultivoCampania")

    relation_specs = (
        (SetupCultivo, data.setups, "SetupCultivo", lambda a, b, v: ({"cultivo_previo": crops[a], "cultivo_siguiente": crops[b]}, {"dias": v})),
        (SecuenciaPermitida, data.secuencias, "SecuenciaPermitida", lambda a, b, v: ({"cultivo_previo": crops[a], "cultivo_siguiente": crops[b]}, {"permitido": v})),
        (CompatibilidadCultivoSuelo, data.compatibilidades, "CompatibilidadCultivoSuelo", lambda a, b, v: ({"cultivo": crops[a], "tipo_suelo": soils[b]}, {"compatible": v})),
        (RendimientoCultivoSuelo, data.rendimientos, "RendimientoCultivoSuelo", lambda a, b, v: ({"tipo_suelo": soils[a], "cultivo": crops[b]}, {"valor": v})),
        (ImpactoRotacion, data.rotaciones, "ImpactoRotacion", lambda a, b, v: ({"cultivo_previo": crops[a], "cultivo_actual": crops[b]}, {"valor": v})),
    )
    for model, values, label, mapping in relation_specs:
        ids = []
        for (first, second), value in values.items():
            lookup, defaults = mapping(first, second, value)
            ids.append(_upsert(model, lookup, defaults, stats, label).pk)
        _delete_queryset(model.objects.exclude(pk__in=ids), stats, label)

    history_ids = []
    for (crop_code, lot_code, historical_code), present in data.historial.items():
        obj = _upsert(
            HistorialLoteCultivo,
            {"cultivo": crops[crop_code], "lote": lots[lot_code], "campania_historica": historical[historical_code]},
            {"presente": present},
            stats,
            "HistorialLoteCultivo",
        )
        history_ids.append(obj.pk)
    _delete_queryset(HistorialLoteCultivo.objects.exclude(pk__in=history_ids), stats, "HistorialLoteCultivo")
    return stats
