import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from core.services.economic_indicators import build_economic_indicators
from core.models import (
    Lote,
    Cultivo,
    Costo,
    TipoCosto,
    Campania,
    Planificacion,
    AsignacionLoteSlot,
    TipoSuelo,
    RendimientoCultivoSuelo,
    CompatibilidadCultivoSuelo,
    HistorialLoteCultivo
)
from datetime import datetime, timedelta
import math
import unicodedata


def _build_gantt_data(asignaciones):
    """Construye los datos del Gantt a partir de asignaciones de una planificación."""
    base_year = datetime.now().year
    base_date = datetime(base_year, 6, 1)

    lotes_list = sorted(list(set(asig.lote.codigo for asig in asignaciones)))
    y_pos = {lote_cod: idx for idx, lote_cod in enumerate(lotes_list)}

    gantt_data = []
    for asig in asignaciones:
        st_date = base_date + timedelta(days=int(asig.dia_siembra) - 1)
        ht_date = base_date + timedelta(days=int(asig.dia_cosecha) - 1)
        duration = (ht_date - st_date).days

        gantt_data.append({
            "lote": asig.lote.codigo,
            "y_pos": y_pos[asig.lote.codigo],
            "cultivo": asig.cultivo.codigo,
            "slot": asig.slot.codigo,
            "fecha_siembra": st_date.strftime("%d/%m/%Y"),
            "fecha_cosecha": ht_date.strftime("%d/%m/%Y"),
            "duration": duration,
            "dia_siembra": asig.dia_siembra,
            "dia_cosecha": asig.dia_cosecha,
            "ingreso": asig.ingreso,
            "costo": asig.costo,
            "profit": asig.ingreso - asig.costo if asig.ingreso is not None and asig.costo is not None else 0
        })

    return gantt_data, lotes_list

@login_required(login_url="login")
def home(request):
    total_lotes = Lote.objects.count()
    total_cultivos = Cultivo.objects.count()
    total_planificaciones = Planificacion.objects.count()

    context = {
        "total_lotes": total_lotes,
        "total_cultivos": total_cultivos,
        "total_planificaciones": total_planificaciones,
    }
    return render(request, "core/index.html", context)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        usuario = request.POST.get("username")
        clave = request.POST.get("password")

        user = authenticate(request, username=usuario, password=clave)
        if user is not None:
            login(request, user)
            return redirect("home")
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")

    return render(request, "core/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required(login_url="login")
def lote_list(request):
    lotes = Lote.objects.all().select_related("tipo_suelo")

    # Agregar los últimos 3 cultivos históricos a cada lote
    anio_inicio_campania_actual = 2025

    for lote in lotes:
        historial = (
            HistorialLoteCultivo.objects.filter(
                lote=lote,
                presente=True,
            )
            .select_related("cultivo", "campania_historica")
            .order_by("-campania_historica__orden")[:3]
        )

        for h in historial:
            numero = h.campania_historica.orden

            inicio = anio_inicio_campania_actual - numero
            fin = inicio + 1

            h.campania_mostrar = f"{inicio}/{fin}"

        lote.historial = historial

    return render(request, "core/lotes_list.html", {"lotes": lotes})
    tipos_suelo = TipoSuelo.objects.all().order_by("codigo")
    return render(request, "core/lotes_list.html", {"lotes": lotes, "tipos_suelo": tipos_suelo})


@login_required(login_url="login")
def lote_create(request):
    if request.method == "POST":
        codigo = request.POST.get("codigo")
        nombre = request.POST.get("nombre", "")
        superficie_ha = request.POST.get("superficie_ha")
        max_cultivos_principales = request.POST.get("max_cultivos_principales")
        max_cultivos_secundarios = request.POST.get("max_cultivos_secundarios")
        tipo_suelo_id = request.POST.get("tipo_suelo")

        if codigo and superficie_ha and max_cultivos_principales and max_cultivos_secundarios and tipo_suelo_id:
            try:
                tipo_suelo = TipoSuelo.objects.get(id=tipo_suelo_id)
                Lote.objects.create(
                    codigo=codigo.strip().upper(),
                    nombre=nombre.strip() or codigo.strip().upper(),
                    superficie_ha=float(superficie_ha),
                    max_cultivos_principales=int(max_cultivos_principales),
                    max_cultivos_secundarios=int(max_cultivos_secundarios),
                    tipo_suelo=tipo_suelo
                )
                messages.success(request, f"Lote {codigo} creado con éxito.")
            except Exception as e:
                messages.error(request, f"Error al crear lote: {str(e)}")
        else:
            messages.error(request, "Todos los campos son obligatorios.")

    return lote_list(request)


@login_required(login_url="login")
def cultivo_list(request, form_data=None, open_modal=False):
    cultivos = Cultivo.objects.exclude(codigo="BARBECHO").prefetch_related("rendimientocultivosuelo_set__tipo_suelo").order_by("codigo")
    tipos_suelo = list(TipoSuelo.objects.all().order_by("codigo"))
    form_data = form_data or {}
    base_year = datetime.now().year
    base_date = datetime(base_year, 6, 1)

    for suelo in tipos_suelo:
        suelo.form_value = form_data.get(f"rendimiento_{suelo.id}", "")

    for cultivo in cultivos:
        # Calcular fechas de inicio y fin asumiendo campaña del 01/06 al 31/05 del año siguiente
        st_date = base_date + timedelta(days=int(cultivo.siembra_inicio) - 1)
        ht_date = base_date + timedelta(days=int(cultivo.siembra_fin) - 1)
        cultivo.siembra_inicio_fecha = st_date.strftime("%d/%m/%Y")
        cultivo.siembra_fin_fecha = ht_date.strftime("%d/%m/%Y")
        cultivo.siembra_inicio_pct = (int(cultivo.siembra_inicio) / 365) * 100
        cultivo.siembra_fin_pct = ((int(cultivo.siembra_fin) + 1) / 365) * 100

        # Rendimientos por tipo de suelo
        cultivo.rendimientos = [
            {
                "suelo": str(r.tipo_suelo),
                "valor": r.valor
            }
            for r in cultivo.rendimientocultivosuelo_set.all().order_by("tipo_suelo__codigo")
        ]

    min_date = f"{base_year}-06-01"
    max_date = f"{base_year + 1}-05-31"

    return render(
        request,
        "core/cultivos_list.html",
        {
            "cultivos": cultivos,
            "tipos_suelo": tipos_suelo,
            "min_date": min_date,
            "max_date": max_date,
            "form_data": form_data,
            "open_modal": open_modal,
        }
    )


@login_required(login_url="login")
def cultivo_create(request):
    if request.method == "POST":
        nombre = request.POST.get("nombre")
        form_data = request.POST.dict()
        form_data["no_repetir_sin_intermedio"] = request.POST.get("no_repetir_sin_intermedio") == "on"
        codigo = (
            unicodedata.normalize("NFD", nombre)
            .encode("ascii", "ignore")
            .decode("utf-8")
            .upper()
            .strip()
        ) if nombre else ""
        tipo = request.POST.get("tipo")
        
        if nombre and Cultivo.objects.filter(nombre__iexact=nombre.strip()).exists():
            messages.error(
                request,
                f"Ya existe un cultivo con el nombre '{nombre}'."
            )
            return cultivo_list(request, form_data=form_data, open_modal=True)

        if Cultivo.objects.filter(codigo=codigo).exists():
            messages.error(
                request,
                f"Ya existe un cultivo con el código '{codigo}'."
            )
            return cultivo_list(request, form_data=form_data, open_modal=True)
        
        duracion_dias = request.POST.get("duracion_dias")
        siembra_inicio_fecha_str = request.POST.get("siembra_inicio_fecha")
        siembra_fin_fecha_str = request.POST.get("siembra_fin_fecha")
        no_repetir = request.POST.get("no_repetir_sin_intermedio") == "on"

        if codigo and nombre and tipo and duracion_dias and siembra_inicio_fecha_str and siembra_fin_fecha_str:
            try:
                base_year = datetime.now().year
                base_date = datetime(base_year, 6, 1)

                inicio_dt = datetime.strptime(siembra_inicio_fecha_str, "%Y-%m-%d")
                fin_dt = datetime.strptime(siembra_fin_fecha_str, "%Y-%m-%d")

                siembra_inicio = (inicio_dt - base_date).days + 1
                siembra_fin = (fin_dt - base_date).days + 1

                if siembra_fin < siembra_inicio:
                    messages.error(request, "La fecha de fin de siembra no puede ser anterior a la de inicio.")
                    return cultivo_list(request, form_data=form_data, open_modal=True)

                from django.db import transaction
                with transaction.atomic():
                    cultivo = Cultivo.objects.create(
                        codigo=codigo.strip().upper(),
                        nombre=nombre.strip(),
                        tipo=tipo,
                        duracion_dias=int(duracion_dias),
                        siembra_inicio=siembra_inicio,
                        siembra_fin=siembra_fin,
                        no_repetir_sin_intermedio=no_repetir,
                        habilitado_optimizacion=False,
                    )
                    
                    # Crear rendimientos y compatibilidades por cada tipo de suelo
                    tipos_suelo = TipoSuelo.objects.all()
                    for suelo in tipos_suelo:
                        rend_val = request.POST.get(f"rendimiento_{suelo.id}", 0.0)
                        RendimientoCultivoSuelo.objects.create(
                            cultivo=cultivo,
                            tipo_suelo=suelo,
                            valor=float(rend_val)
                        )
                        CompatibilidadCultivoSuelo.objects.create(
                            cultivo=cultivo,
                            tipo_suelo=suelo,
                            compatible=True
                        )

                    tipos_costo = {
                        tipo.codigo: tipo
                        for tipo in TipoCosto.objects.filter(
                            codigo__in=[
                                "fsp", "sc", "hc", "frc", "vr", "tf",
                                "scp", "cp", "st", "cst", "clt",
                            ]
                        )
                    }
                    campanias = list(Campania.objects.order_by("orden"))
                    lotes = list(Lote.objects.order_by("codigo"))
                    costos = []

                    for codigo_tipo in ("tf", "scp", "st"):
                        if codigo_tipo in tipos_costo:
                            costos.append(Costo(
                                cultivo=cultivo,
                                tipo_costo=tipos_costo[codigo_tipo],
                                valor=0,
                                configurado=False,
                            ))

                    for codigo_tipo in ("fsp", "sc", "hc", "cp", "cst", "clt"):
                        if codigo_tipo in tipos_costo:
                            costos.extend(
                                Costo(
                                    cultivo=cultivo,
                                    tipo_costo=tipos_costo[codigo_tipo],
                                    campania=campania,
                                    valor=0,
                                    configurado=False,
                                )
                                for campania in campanias
                            )

                    for codigo_tipo in ("frc", "vr"):
                        if codigo_tipo in tipos_costo:
                            costos.extend(
                                Costo(
                                    cultivo=cultivo,
                                    tipo_costo=tipos_costo[codigo_tipo],
                                    campania=campania,
                                    lote=lote,
                                    valor=0,
                                    configurado=False,
                                )
                                for campania in campanias
                                for lote in lotes
                            )

                    Costo.objects.bulk_create(costos)
                messages.success(
                    request,
                    f"Cultivo {codigo} creado. Completa sus precios y costos antes de habilitarlo.",
                )
            except Exception as e:
                messages.error(request, f"Error al crear cultivo: {str(e)}")
                return cultivo_list(request, form_data=form_data, open_modal=True)
        else:
            messages.error(request, "Todos los campos son obligatorios.")
            return cultivo_list(request, form_data=form_data, open_modal=True)

    return cultivo_list(request)


@login_required(login_url="login")
def costo_list(request):
    selected_tab = request.GET.get("tab", "detalle")
    if selected_tab not in {"margenes", "indiferencia", "detalle"}:
        selected_tab = "detalle"
    selected_tipo = request.GET.get("tipo", "")
    selected_campania = request.GET.get("campania", "")
    selected_cultivo = request.GET.get("cultivo", "")
    ri_view = request.GET.get("ri_view", "grafico")
    if ri_view not in {"lista", "grafico"}:
        ri_view = "grafico"
    ri_selected_campanias = request.GET.getlist("ri_campania")
    ri_selected_suelos = request.GET.getlist("ri_suelo")
    ri_selected_cultivos = request.GET.getlist("ri_cultivo")
    ri_cultivo_mode = request.GET.get("ri_cultivo_mode", "selected")
    if ri_cultivo_mode not in {"all", "selected"}:
        ri_cultivo_mode = "selected"
    if "ri_cultivo_mode" not in request.GET and not ri_selected_cultivos:
        primer_cultivo = (
            Cultivo.objects.exclude(
                Q(codigo__iexact="BARBECHO") | Q(nombre__iexact="BARBECHO")
            )
            .order_by("codigo")
            .first()
        )
        if primer_cultivo:
            ri_selected_cultivos = [str(primer_cultivo.id)]
    selected_page = request.GET.get("page", "1")
    selected_arrendamiento_page = request.GET.get("arrendamiento_page", "1")
    selected_cultivo_obj = None

    if selected_cultivo:
        selected_cultivo_obj = Cultivo.objects.filter(pk=selected_cultivo).first()

    if request.method == "POST":
        posted_values = {
            key.removeprefix("costo_"): value.strip().replace(",", ".")
            for key, value in request.POST.items()
            if key.startswith("costo_")
        }
        updates = []
        errors = []

        for costo_id, raw_value in posted_values.items():
            try:
                value = float(raw_value)
                if value < 0:
                    raise ValueError("negative")
                updates.append((int(costo_id), value))
            except (TypeError, ValueError):
                errors.append(costo_id)

        if errors:
            messages.error(request, "Los valores deben ser números mayores o iguales a cero.")
        else:
            with transaction.atomic():
                costos_by_id = Costo.objects.in_bulk([costo_id for costo_id, _ in updates])
                changed = 0
                for costo_id, value in updates:
                    costo = costos_by_id.get(costo_id)
                    if costo is None:
                        continue
                    if costo.valor != value:
                        costo.valor = value
                        changed += 1
                    costo.configurado = True
                    costo.save(update_fields=["valor", "configurado"])

                if request.POST.get("action") == "enable" and selected_cultivo_obj:
                    pendientes = selected_cultivo_obj.costo_set.filter(
                        configurado=False
                    ).count()
                    if pendientes:
                        messages.error(
                            request,
                            f"Todavía faltan revisar {pendientes} valores antes de habilitar el cultivo.",
                        )
                    else:
                        selected_cultivo_obj.habilitado_optimizacion = True
                        selected_cultivo_obj.save(update_fields=["habilitado_optimizacion"])
                        messages.success(
                            request,
                            f"Cultivo {selected_cultivo_obj.codigo} habilitado para optimización.",
                        )
            messages.success(request, f"Se actualizaron {changed} valores de precios y costos.")

    barbecho_costo_q = Q(cultivo__codigo__iexact="BARBECHO") | Q(
        cultivo__nombre__iexact="BARBECHO"
    )
    barbecho_cultivo_q = Q(codigo__iexact="BARBECHO") | Q(
        nombre__iexact="BARBECHO"
    )
    costos = Costo.objects.select_related(
        "cultivo", "tipo_costo", "campania", "lote"
    ).exclude(barbecho_costo_q).order_by(
        "tipo_costo__codigo", "cultivo__codigo", "campania__orden", "lote__codigo"
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
    
    # Mostrar las campañas como años (2025/2026, 2026/2027, ...)
    anio_inicio_campania_actual = 2025

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

    anio_inicio_campania_actual = 2025

    campanias = Campania.objects.order_by("orden")

    for campania in campanias:
        inicio = anio_inicio_campania_actual + (campania.orden - 1)
        fin = inicio + 1
        campania.nombre_mostrar = f"{inicio}/{fin}"
        
    TRADUCCIONES_TIPO_COSTO = {
        "fsp": "Precio futuro de venta",
        "sc": "Costo de cultivo",
        "hc": "Costo de cosecha",
        "frc": "Costo fijo de arrendamiento",
        "vr": "Costo variable de arrendamiento",
        "tf": "Comisión de comercialización",
        "scp": "Producción acondicionada",
        "cp": "Costo de acondicionamiento",
        "st": "Proporción de transporte corto / embolsado",
        "cst": "Costo de flete corta distancia",
        "clt": "Costo de flete larga distancia",
    }
    
    tipos_costo = TipoCosto.objects.order_by("codigo")

    for tipo in tipos_costo:
        tipo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            tipo.codigo,
            tipo.descripcion,
        )
    
    for costo in page_obj.object_list:
        costo.tipo_costo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            costo.tipo_costo.descripcion,
        )

    for costo in arrendamiento_page_obj.object_list:
        costo.tipo_costo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            costo.tipo_costo.descripcion,
        )

    show_costo_cultivo_help = any(
        tipo.codigo == "sc" and str(tipo.id) == selected_tipo
        for tipo in tipos_costo
    )
    
    indicator_data = build_economic_indicators()
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
        for row in indicator_data["margins"]
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
    suelos = TipoSuelo.objects.order_by("codigo")
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
    context = {
        "costos": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "costos_arrendamiento": arrendamiento_page_obj.object_list,
        "arrendamiento_page_obj": arrendamiento_page_obj,
        "arrendamiento_paginator": arrendamiento_paginator,
        "show_costos_generales": show_costos_generales,
        "show_costos_arrendamiento": show_costos_arrendamiento,
        "tipos_costo": tipos_costo,
        "campanias": campanias,
        "cultivos": Cultivo.objects.exclude(barbecho_cultivo_q).order_by("codigo"),
        "selected_tipo": selected_tipo,
        "selected_campania": selected_campania,
        "selected_cultivo": selected_cultivo,
        "selected_page": selected_page,
        "selected_tab": selected_tab,
        "show_standard_indicator_filters": selected_tab == "margenes" or (
            selected_tab == "indiferencia" and ri_view == "lista"
        ),
        "show_costo_cultivo_help": show_costo_cultivo_help,
        "margenes": margenes,
        "indiferencias": indiferencias,
        "ri_view": ri_view,
        "ri_selected_campanias": ri_selected_campanias,
        "ri_selected_suelos": ri_selected_suelos,
        "ri_selected_cultivos": ri_selected_cultivos,
        "ri_cultivo_mode": ri_cultivo_mode,
        "suelos": suelos,
        "ri_chart_data": json.dumps(ri_chart_data),
        "ri_chart_has_data": bool(ri_chart_rows),
        "ri_chart_legend": ri_chart_legend,
        "ri_chart_campaign_count": len(
            {row["campania_id"] for row in ri_chart_rows}
        ),
        "ri_chart_soil_count": len({row["suelo_id"] for row in ri_chart_rows}),
        "ri_maximo": ri_maximo,
        "ri_maximo_kg": (
            round(ri_maximo["rendimiento_indiferencia"] * 1000)
            if ri_maximo
            else None
        ),
        "selected_cultivo_obj": selected_cultivo_obj,
        "costos_pendientes": (
            selected_cultivo_obj.costo_set.filter(configurado=False).count()
            if selected_cultivo_obj else 0
        ),
    }
    return render(request, "core/costos_list.html", context)


@login_required(login_url="login")
def planificacion_list(request):
    planificaciones = Planificacion.objects.all().order_by("-fecha_creacion")
    return render(
        request,
        "core/planificaciones.html",
        {"planificaciones": planificaciones},
    )


@login_required(login_url="login")
def ejecutar_optimizacion(request):
    if request.method == "POST":
        nombre = request.POST.get("nombre", f"Planificación {datetime.now().strftime('%d/%m/%Y %H:%M')}")

        # Crear planificación pendiente
        planificacion = Planificacion.objects.create(
            nombre=nombre,
            estado=Planificacion.Estado.PENDIENTE
        )

        return redirect("planificacion_status", pk=planificacion.id)

    return redirect("planificacion_list")


@login_required(login_url="login")
def planificacion_status(request, pk):
    planificacion = get_object_or_404(Planificacion, pk=pk)

    if planificacion.estado == Planificacion.Estado.COMPLETADO:
        asignaciones = planificacion.asignaciones.select_related(
            "lote", "cultivo", "slot"
        ).order_by("lote__codigo", "slot__orden")
        gantt_data, lotes_list = _build_gantt_data(asignaciones)
        context = {
            "planificacion": planificacion,
            "gantt_data": gantt_data,
            "lotes_list": lotes_list,
        }
        return render(request, "core/resultados_planificacion.html", context)

    if planificacion.estado == Planificacion.Estado.ERROR:
        return render(
            request,
            "core/resultados_planificacion.html",
            {
                "error": "Ocurrió un error al ejecutar el solver. Verifica la configuración de datos en tu base de datos.",
                "planificacion": planificacion,
            },
        )

    # PENDIENTE o EJECUTANDO: mostrar página de espera con polling
    return render(request, "core/planificacion_status.html", {"planificacion": planificacion})


@login_required(login_url="login")
def planificacion_status_partial(request, pk):
    """Fragmento para actualización vía HTMX (polling)."""
    planificacion = get_object_or_404(Planificacion, pk=pk)

    if planificacion.estado == Planificacion.Estado.COMPLETADO:
        asignaciones = planificacion.asignaciones.select_related(
            "lote", "cultivo", "slot"
        ).order_by("lote__codigo", "slot__orden")
        gantt_data, lotes_list = _build_gantt_data(asignaciones)
        context = {
            "planificacion": planificacion,
            "gantt_data": gantt_data,
            "lotes_list": lotes_list,
        }
        return render(request, "core/resultados_planificacion.html", context)

    if planificacion.estado == Planificacion.Estado.ERROR:
        return render(
            request,
            "core/resultados_planificacion.html",
            {
                "error": "Ocurrió un error al ejecutar el solver. Verifica la configuración de datos en tu base de datos.",
                "planificacion": planificacion,
            },
        )

    # Sigue pendiente o ejecutando: devolver fragmento de espera
    return render(request, "core/planificacion_status.html", {"planificacion": planificacion})
