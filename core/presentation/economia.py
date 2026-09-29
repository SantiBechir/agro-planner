import json

from core.services.costos import COMPONENTES_SIEMBRA

TRADUCCIONES_TIPO_COSTO = {
    "fsp": "Precio futuro de venta",
    "sc_seed": "Semillas",
    "sc_agro": "Agroquímicos",
    "sc_fert": "Fertilizantes",
    "sc_labor": "Labores",
    "sc_structure": "Estructura",
    "hc": "Costo de cosecha",
    "frc": "Costo fijo de arrendamiento",
    "vr": "Costo variable de arrendamiento",
    "tf": "Comision de comercializacion",
    "scp": "Produccion acondicionada",
    "cp": "Costo de acondicionamiento",
    "st": "Proporcion de transporte corto / embolsado",
    "cst": "Costo de flete corta distancia",
    "clt": "Costo de flete larga distancia",
}

DETALLES_TIPO_COSTO = {
    "fsp": "Precio esperado de venta del grano por tonelada.",
    "sc_seed": "Costo de semillas por hectárea.",
    "sc_agro": "Costo de agroquímicos por hectárea.",
    "sc_fert": "Costo de fertilizantes por hectárea.",
    "sc_labor": "Costo de labores por hectárea.",
    "sc_structure": "Costo de estructura por hectárea.",
    "hc": "Incluye las labores y servicios asociados a la cosecha.",
    "frc": "Cargo fijo de arrendamiento por cultivo, lote y campania.",
    "vr": "Cargo variable de arrendamiento como porcentaje del ingreso por cultivo, lote y campania.",
    "tf": "Comision de comercializacion aplicada sobre el precio de venta.",
    "scp": "Porcentaje de la produccion que requiere acondicionamiento.",
    "cp": "Costo unitario para acondicionar la produccion.",
    "st": "Proporcion de la produccion con transporte corto o embolsado.",
    "cst": "Costo unitario del flete de corta distancia.",
    "clt": "Costo unitario del flete de larga distancia.",
}


def decorar_catalogos(page_obj, arrendamiento_page_obj, campanias, tipos_costo, anio_inicio_campania_actual):
    for costo in page_obj.object_list:
        if costo.campania:
            numero = costo.campania.orden

            inicio = anio_inicio_campania_actual + (numero - 1)
            fin = inicio + 1

            costo.campania_mostrar = f"{inicio}/{fin}"
        else:
            costo.campania_mostrar = "Global"
    for costo in arrendamiento_page_obj.object_list:
        if costo.campania:
            inicio = anio_inicio_campania_actual + (costo.campania.orden - 1)
            costo.campania_mostrar = f"{inicio}/{inicio + 1}"
        else:
            costo.campania_mostrar = "Global"


    for campania in campanias:
        inicio = anio_inicio_campania_actual + (campania.orden - 1)
        fin = inicio + 1
        campania.nombre_mostrar = f"{inicio}/{fin}"


    for tipo in tipos_costo:
        tipo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            tipo.codigo,
            tipo.descripcion,
        )
        tipo.detalle_mostrar = DETALLES_TIPO_COSTO.get(tipo.codigo, "")

    for costo in page_obj.object_list:
        costo.tipo_costo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            costo.tipo_costo.descripcion,
        )
        costo.es_componente_siembra = (
            costo.tipo_costo.codigo in COMPONENTES_SIEMBRA
            and costo.campania_id is not None
        )
        costo.grupo_siembra = (
            f"{costo.cultivo_id}-{costo.campania_id}"
            if costo.es_componente_siembra
            else ""
        )

    for costo in arrendamiento_page_obj.object_list:
        costo.tipo_costo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            costo.tipo_costo.descripcion,
        )



def filtrar_indicadores(indicator_data, *, selected_campania="", selected_cultivo="", selected_suelo=""):
    if selected_campania:
        indicator_data = {
            key: [
                row
                for row in rows
                if str(row["campania_id"]) == selected_campania
            ]
            for key, rows in indicator_data.items()
        }
    if selected_cultivo:
        indicator_data = {
            key: [
                row
                for row in rows
                if str(row["cultivo_id"]) == selected_cultivo
            ]
            for key, rows in indicator_data.items()
        }
    if selected_suelo:
        indicator_data = {
            key: [
                row
                for row in rows
                if str(row["suelo_id"]) == selected_suelo
            ]
            for key, rows in indicator_data.items()
        }
    return indicator_data


def preparar_tablas(indicator_data):
    margin_indicator_rows = indicator_data["margins"]
    margenes = [
        {
            "cultivo": row["cultivo"],
            "campania": row["campania"],
            "suelo": row["suelo"],
            "nivel_mostrar": {"A": "Alto", "M": "Medio", "B": "Bajo"}.get(
                row["nivel"], row["nivel"]
            ),
            "rendimiento_promedio": row["rendimiento"],
            "ingreso": row["ingreso_bruto"],
            "costos_directos": row["costos_directos"],
            "margen": row["margen_bruto"],
            "margen_con_arrendamiento": row["margen_con_arrendamiento"],
        }
        for row in margin_indicator_rows
    ]
    indiferencias = [
        {
            "cultivo": row["cultivo"],
            "campania": row["campania"],
            "suelo": row["suelo"],
            "nivel_mostrar": {"A": "Alto", "M": "Medio", "B": "Bajo"}.get(
                row["nivel"], row["nivel"]
            ),
            "rendimiento_estimado": row["rendimiento_estimado"],
            "precio_neto": row["precio_neto"],
            "rendimiento_indiferencia": row["rendimiento_indiferencia"],
        }
        for row in indicator_data["break_even"]
    ]
    indiferencias_agrupadas = {}
    for fila in indiferencias:
        clave = (fila["cultivo"], fila["campania"], fila["suelo"])
        agrupada = indiferencias_agrupadas.setdefault(
            clave,
            {
                "cultivo": fila["cultivo"],
                "campania": fila["campania"],
                "suelo": fila["suelo"],
                "rendimiento_alto": None,
                "rendimiento_medio": None,
                "rendimiento_bajo": None,
                "precio_neto": fila["precio_neto"],
                "rendimiento_indiferencia": fila["rendimiento_indiferencia"],
            },
        )
        rendimiento_por_nivel = {"Alto": "rendimiento_alto", "Medio": "rendimiento_medio", "Bajo": "rendimiento_bajo"}
        campo = rendimiento_por_nivel.get(fila["nivel_mostrar"])
        if campo:
            agrupada[campo] = fila["rendimiento_estimado"]
    indiferencias_agrupadas = sorted(
        indiferencias_agrupadas.values(),
        key=lambda fila: (fila["cultivo"], fila["campania"], fila["suelo"]),
    )
    return {"margenes": margenes, "indiferencias": indiferencias, "indiferencias_agrupadas": indiferencias_agrupadas}


def preparar_graficos_margen(margin_indicator_rows, *, mb_selected_campanias, mb_selected_suelos, mb_selected_cultivos, mb_cultivo_mode):
    mb_rows = list(margin_indicator_rows)
    if mb_selected_campanias:
        mb_rows = [
            row for row in mb_rows
            if str(row["campania_id"]) in mb_selected_campanias
        ]
    if mb_selected_suelos:
        mb_rows = [
            row for row in mb_rows if str(row["suelo_id"]) in mb_selected_suelos
        ]
    if mb_cultivo_mode == "selected":
        mb_rows = [
            row for row in mb_rows
            if str(row["cultivo_id"]) in mb_selected_cultivos
        ]
    mb_cost_labels = [
        "Costo de cultivo", "Costo de cosecha", "Comercializaci\u00f3n",
        "Acondicionamiento", "Flete", "Arrendamiento",
    ]
    mb_cost_colors = ["#166534", "#4d8b4f", "#2563b9", "#eab308", "#f97316", "#7c3aed"]
    mb_cost_color_by_field = {
        "costo_cultivo": mb_cost_colors[0],
        "costo_cosecha": mb_cost_colors[1],
        "costo_comercializacion": mb_cost_colors[2],
        "costo_acondicionamiento": mb_cost_colors[3],
        "costo_flete": mb_cost_colors[4],
        "costo_arrendamiento": mb_cost_colors[5],
    }
    conceptos_margen = [
        ("Precio cosecha (USD/t)", "precio_cosecha"),
        ("Rinde esperado (t/ha)", "rendimiento"),
        ("Ingreso bruto (USD/ha)", "ingreso_bruto"),
        ("Costo de cultivo (USD/ha)", "costo_cultivo"),
        ("Costo de cosecha (USD/ha)", "costo_cosecha"),
        ("Comercialización (USD/ha)", "costo_comercializacion"),
        ("Acondicionamiento (USD/ha)", "costo_acondicionamiento"),
        ("Flete (USD/ha)", "costo_flete"),
        ("Subtotal costos (USD/ha)", "subtotal_costos"),
        ("Margen bruto (USD/ha)", "margen_bruto"),
        ("Costo arrendamiento (USD/ha)", "costo_arrendamiento"),
        ("Margen c/arrendamiento (USD/ha)", "margen_con_arrendamiento"),
        ("RI (t/ha)", "rendimiento_indiferencia"),
    ]
    mb_grupos = {}
    for row in mb_rows:
        clave = (row["cultivo_id"], row["campania_id"], row["suelo_id"])
        grupo = mb_grupos.setdefault(
            clave,
            {
                "cultivo": row["cultivo"],
                "suelo": row["suelo"],
                "campania": row["campania"],
                "niveles": {},
            },
        )
        grupo["niveles"][row["nivel"]] = row
    mb_cost_charts = []
    for grupo in sorted(
        mb_grupos.values(),
        key=lambda item: (item["cultivo"], item["campania"], item["suelo"]),
    ):
        row = grupo["niveles"].get("M") or next(iter(grupo["niveles"].values()))
        values = [
            round(row["costo_cultivo"], 2),
            round(row["costo_cosecha"], 2),
            round(row["costo_comercializacion"], 2),
            round(row["costo_acondicionamiento"], 2),
            round(row["costo_flete"], 2),
            round(row["costo_arrendamiento"], 2),
        ]
        total = sum(values)
        mb_cost_charts.append({
            "cultivo": grupo["cultivo"],
            "suelo": grupo["suelo"],
            "campania": grupo["campania"],
            "chart_data": json.dumps({
                "labels": mb_cost_labels,
                "datasets": [{
                    "data": values,
                    "backgroundColor": mb_cost_colors,
                    "borderWidth": 2,
                    "borderColor": "#ffffff",
                }],
            }),
            "detalle": [
                {
                    "label": label,
                    "color": mb_cost_color_by_field.get(campo),
                    "row_color": (
                        f"{mb_cost_color_by_field[campo]}18"
                        if campo in mb_cost_color_by_field else ""
                    ),
                    "alto": grupo["niveles"].get("A", {}).get(campo),
                    "medio": grupo["niveles"].get("M", {}).get(campo),
                    "bajo": grupo["niveles"].get("B", {}).get(campo),
                }
                for label, campo in conceptos_margen
            ],
        })

    return mb_cost_charts


def preparar_grafico_indiferencia(indicator_data, *, ri_selected_campanias, ri_selected_suelos, ri_selected_cultivos, ri_cultivo_mode):
    ri_chart_rows = [
        row
        for row in indicator_data["break_even"]
        if row["nivel"] == "M" and row["rendimiento_indiferencia"] is not None
    ]
    if ri_selected_campanias:
        ri_chart_rows = [
            row
            for row in ri_chart_rows
            if str(row["campania_id"]) in ri_selected_campanias
        ]
    if ri_selected_suelos:
        ri_chart_rows = [
            row for row in ri_chart_rows if str(row["suelo_id"]) in ri_selected_suelos
        ]
    if ri_cultivo_mode == "selected":
        ri_chart_rows = [
            row
            for row in ri_chart_rows
            if str(row["cultivo_id"]) in ri_selected_cultivos
        ]

    chart_labels = sorted({row["cultivo"] for row in ri_chart_rows})
    chart_groups = {}
    for row in ri_chart_rows:
        group = (row["suelo_id"], row["campania_id"])
        chart_groups.setdefault(
            group,
            {
                "suelo": row["suelo"],
                "campania": row["campania"],
                "campania_id": row["campania_id"],
                "values": {},
            },
        )["values"][row["cultivo"]] = round(
            row["rendimiento_indiferencia"] * 1000, 0
        )
    campaign_ids = sorted({row["campania_id"] for row in ri_chart_rows})
    campaign_position = {campania_id: index for index, campania_id in enumerate(campaign_ids)}
    soil_colors = {
        "Molisol": "#4d8b4f",
        "Alfisol": "#4f86d9",
        "Vertisol": "#f59e0b",
    }

    def campaign_tone(base_color, position):
        """Keep a soil's hue and lighten it for later campaigns."""
        red, green, blue = (int(base_color[index : index + 2], 16) for index in (1, 3, 5))
        lightness = min(position * 0.22, 0.55)
        return "#{:02x}{:02x}{:02x}".format(
            round(red + (255 - red) * lightness),
            round(green + (255 - green) * lightness),
            round(blue + (255 - blue) * lightness),
        )

    ordered_chart_groups = sorted(
        chart_groups.values(), key=lambda group: (group["campania_id"], group["suelo"])
    )
    ri_chart_data = {
        "labels": chart_labels,
        "datasets": [
            {
                "label": f"{group['suelo']} · {group['campania']}",
                "data": [group["values"].get(cultivo) for cultivo in chart_labels],
                "backgroundColor": campaign_tone(
                    soil_colors.get(group["suelo"], "#64748b"),
                    campaign_position[group["campania_id"]],
                ),
                "borderRadius": 6,
                "maxBarThickness": 42,
            }
            for group in ordered_chart_groups
        ],
    }
    ri_chart_legend = [
        {"index": index, "label": dataset["label"], "color": dataset["backgroundColor"]}
        for index, dataset in enumerate(ri_chart_data["datasets"])
    ]
    ri_maximo = max(
        ri_chart_rows,
        key=lambda row: row["rendimiento_indiferencia"],
        default=None,
    )
    return {
        "ri_chart_data": json.dumps(ri_chart_data),
        "ri_chart_has_data": bool(ri_chart_rows),
        "ri_chart_legend": ri_chart_legend,
        "ri_chart_campaign_count": len({row["campania_id"] for row in ri_chart_rows}),
        "ri_chart_soil_count": len({row["suelo_id"] for row in ri_chart_rows}),
        "ri_maximo": ri_maximo,
        "ri_maximo_kg": round(ri_maximo["rendimiento_indiferencia"] * 1000) if ri_maximo else None,
    }
