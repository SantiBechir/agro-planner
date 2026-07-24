from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from core.models import (
    Ambiente,
    Lote,
    Cultivo,
    Costo,
    TipoCosto,
    Campania,
    CampaniaHistorica,
    Planificacion,
    AsignacionLoteSlot,
    TipoSuelo,
    RendimientoCultivoSuelo,
    CompatibilidadCultivoSuelo,
    HistorialLoteCultivo
)
from datetime import datetime, timedelta
import math
import re


RENTAL_COST_CODES = ("frc", "vr")
BARBECHO_COST_Q = Q(cultivo__codigo__icontains="BARBECHO") | Q(
    cultivo__nombre__icontains="BARBECHO"
)

TRADUCCIONES_TIPO_COSTO = {
    "fsp": "Precio futuro de venta",
    "sc": "Costo de cultivo",
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
    "sc": (
        "Incluye semillas, fertilizantes, fitosanitarios y labores de implantacion "
        "y manejo. No incluye el costo de arrendamiento."
    ),
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


def _decorate_costo(costo):
    costo.tipo_costo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
        costo.tipo_costo.codigo,
        costo.tipo_costo.descripcion,
    )
    costo.tipo_costo.detalle_mostrar = DETALLES_TIPO_COSTO.get(
        costo.tipo_costo.codigo,
        "",
    )
    if costo.campania:
        inicio = 2025 + (costo.campania.orden - 1)
        costo.campania_mostrar = f"{inicio}/{inicio + 1}"
    else:
        costo.campania_mostrar = "Global"


def _decorate_costos(costos):
    for costo in costos:
        _decorate_costo(costo)


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
def lote_list(
    request,
    create_error=None,
    create_nombre="",
    create_ambientes=None,
):
    lotes = (
        Lote.objects.all()
        .select_related("tipo_suelo")
        .prefetch_related("ambientes__tipo_suelo")
        .prefetch_related(
            Prefetch(
                "historiallotecultivo_set",
                queryset=HistorialLoteCultivo.objects.filter(presente=True)
                .select_related("cultivo", "campania_historica")
                .order_by("-campania_historica__anio_inicio", "cultivo__codigo"),
                to_attr="historial_registros",
            )
        )
        .order_by("codigo")
    )

    for lote in lotes:
        # Group history by campaign: one entry per campaign holding 1-2 crops
        campanias_map = {}
        for h in lote.historial_registros:
            key = h.campania_historica_id
            if key not in campanias_map:
                campanias_map[key] = {
                    "codigo": h.campania_historica.codigo,
                    "anio_inicio": h.campania_historica.anio_inicio,
                    "campania_mostrar": h.campania_historica.etiqueta,
                    "cultivos": [],
                }
            campanias_map[key]["cultivos"].append(h)

        # Most recent campaign first
        lote.historial = sorted(
            campanias_map.values(),
            key=lambda c: c["anio_inicio"],
            reverse=True,
        )
        for campania in lote.historial:
            cultivos_historial = campania["cultivos"]
            campania["cultivo_1"] = cultivos_historial[0].cultivo
            campania["rendimiento_1"] = cultivos_historial[0].rendimiento_kg_ha
            if len(cultivos_historial) > 1:
                campania["cultivo_2"] = cultivos_historial[1].cultivo
                campania["rendimiento_2"] = cultivos_historial[1].rendimiento_kg_ha

    # Load window: any finished campaign within the last 15 years
    base_year = CampaniaHistorica.anio_base_actual()
    anios_cargables = [
        {"valor": anio, "etiqueta": f"{anio}/{anio + 1}"}
        for anio in range(base_year - 1, base_year - 16, -1)
    ]

    context = {
        "lotes": lotes,
        "tipos_suelo": TipoSuelo.objects.all().order_by("codigo"),
        "cultivos": Cultivo.objects.all().order_by("codigo"),
        "anios_cargables": anios_cargables,
        "create_error": create_error,
        "create_nombre": create_nombre,
        "create_ambientes": create_ambientes or [
            {"suelo": "", "rendimiento": "", "ha": ""}
        ],
    }
    return render(request, "core/lotes_list.html", context)


def _next_lote_codigo():
    """Return the next auto code J{n+1} based on the highest existing J{n}."""
    max_n = 0
    for codigo in Lote.objects.values_list("codigo", flat=True):
        match = re.fullmatch(r"J(\d+)", codigo or "")
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"J{max_n + 1}"


def _parse_ambientes(request):
    """Validate indexed ambiente fields and return normalized values."""
    indices = sorted(
        {
            int(key.rsplit("_", 1)[1])
            for key in request.POST
            if re.fullmatch(r"(suelo|rendimiento|ha)_\d+", key)
        }
    )
    ambientes_raw = [
        (
            (request.POST.get(f"suelo_{i}") or "").strip(),
            (request.POST.get(f"rendimiento_{i}") or "").strip(),
            (request.POST.get(f"ha_{i}") or "").strip(),
        )
        for i in indices
    ]
    if not ambientes_raw:
        return None, "Debe cargar al menos un ambiente para el lote."

    suelos_by_id = {str(s.id): s for s in TipoSuelo.objects.all()}
    suelos_vistos = set()
    ambientes_data = []
    for suelo_id, rendimiento, ha_raw in ambientes_raw:
        if suelo_id not in suelos_by_id:
            return None, "Cada ambiente debe tener un tipo de suelo válido."
        if suelo_id in suelos_vistos:
            return None, "No puede repetir el mismo tipo de suelo en dos ambientes del lote."
        suelos_vistos.add(suelo_id)
        if rendimiento not in ("A", "M", "B"):
            return None, "El rendimiento esperado debe ser Alto, Medio o Bajo."
        try:
            ha = float(ha_raw)
            if ha <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return None, "La superficie de cada ambiente debe ser un número mayor a cero."
        ambientes_data.append((suelos_by_id[suelo_id], rendimiento, ha))
    return ambientes_data, None


def _raw_ambientes(request):
    """Return submitted ambiente values for redisplaying a failed create form."""
    indices = sorted(
        {
            int(key.rsplit("_", 1)[1])
            for key in request.POST
            if re.fullmatch(r"(suelo|rendimiento|ha)_\d+", key)
        }
    )
    ambientes = [
        {
            "suelo": (request.POST.get(f"suelo_{i}") or "").strip(),
            "rendimiento": (request.POST.get(f"rendimiento_{i}") or "").strip(),
            "ha": (request.POST.get(f"ha_{i}") or "").strip(),
        }
        for i in indices
    ]
    return ambientes or [{"suelo": "", "rendimiento": "", "ha": ""}]


@login_required(login_url="login")
def lote_create(request):
    if request.method == "POST":
        nombre = (request.POST.get("nombre") or "").strip()
        ambientes_raw = _raw_ambientes(request)
        ambientes_data, error = _parse_ambientes(request)
        if not nombre:
            error = "El nombre del lote es obligatorio."
        elif Lote.objects.filter(nombre__iexact=nombre).exists():
            error = f'Ya existe un lote con el nombre "{nombre}".'

        if error is None:
            superficie_total = sum(ha for _, _, ha in ambientes_data)
            # Dominant soil bridge for the solver: soil with the most ha
            suelo_dominante = max(
                ambientes_data, key=lambda item: item[2]
            )[0]

            try:
                with transaction.atomic():
                    lote = Lote.objects.create(
                        codigo=_next_lote_codigo(),
                        nombre=nombre,
                        superficie_ha=superficie_total,
                        max_cultivos_principales=10,
                        max_cultivos_secundarios=10,
                        tipo_suelo=suelo_dominante,
                        habilitado=True,
                    )
                    Ambiente.objects.bulk_create(
                        [
                            Ambiente(
                                lote=lote,
                                tipo_suelo=suelo,
                                rendimiento_esperado=rendimiento,
                                superficie_ha=ha,
                            )
                            for suelo, rendimiento, ha in ambientes_data
                        ]
                    )
            except IntegrityError:
                # The database constraint also protects the gap between the
                # case-insensitive existence check and the insert.
                error = f'Ya existe un lote con el nombre "{nombre}".'
            else:
                messages.success(
                    request,
                    f"Lote {lote.codigo} ({nombre}) creado con éxito.",
                )

        if error is not None:
            return lote_list(
                request,
                create_error=error,
                create_nombre=nombre,
                create_ambientes=ambientes_raw,
            )

    return lote_list(request)


@login_required(login_url="login")
@require_POST
def lote_update(request, pk):
    lote = get_object_or_404(Lote, pk=pk)
    nombre = (request.POST.get("nombre") or "").strip()
    ambientes_data, error = _parse_ambientes(request)
    if not nombre:
        error = "El nombre del lote es obligatorio."
    elif Lote.objects.filter(nombre__iexact=nombre).exclude(pk=lote.pk).exists():
        error = f'Ya existe un lote con el nombre "{nombre}".'

    if error is not None:
        messages.error(request, error)
    else:
        superficie_total = sum(ha for _, _, ha in ambientes_data)
        suelo_dominante = max(ambientes_data, key=lambda item: item[2])[0]
        with transaction.atomic():
            lote.nombre = nombre
            lote.habilitado = request.POST.get("habilitado") == "1"
            lote.superficie_ha = superficie_total
            lote.tipo_suelo = suelo_dominante
            lote.save(update_fields=[
                "nombre", "habilitado", "superficie_ha", "tipo_suelo"
            ])
            lote.ambientes.all().delete()
            Ambiente.objects.bulk_create([
                Ambiente(
                    lote=lote,
                    tipo_suelo=suelo,
                    rendimiento_esperado=rendimiento,
                    superficie_ha=ha,
                )
                for suelo, rendimiento, ha in ambientes_data
            ])
        messages.success(request, f"Lote {lote.codigo} actualizado con éxito.")

    return lote_list(request)


@login_required(login_url="login")
def lote_toggle(request, pk):
    if request.method == "POST":
        lote = get_object_or_404(Lote, pk=pk)
        lote.habilitado = not lote.habilitado
        lote.save(update_fields=["habilitado"])
        estado = "activado" if lote.habilitado else "desactivado"
        messages.success(request, f"Lote {lote.codigo} {estado}.")

    return lote_list(request)


@login_required(login_url="login")
def lote_historial_add(request, pk):
    if request.method == "POST":
        lote = get_object_or_404(Lote, pk=pk)
        anio_raw = (request.POST.get("anio_inicio") or "").strip()
        cultivo_1_id = request.POST.get("cultivo_1")
        rendimiento_1_raw = (request.POST.get("rendimiento_1") or "").strip()
        cultivo_2_id = (request.POST.get("cultivo_2") or "").strip()
        rendimiento_2_raw = (request.POST.get("rendimiento_2") or "").strip()

        def _parse_rendimiento(raw):
            if not raw:
                return None
            try:
                valor = float(raw)
                return valor if valor >= 0 else None
            except ValueError:
                return None

        base_year = CampaniaHistorica.anio_base_actual()
        anio = None
        error_campania = None
        try:
            anio = int(anio_raw)
        except ValueError:
            error_campania = "Debe indicar la campaña y el cultivo principal."
        else:
            if anio > base_year - 1:
                error_campania = (
                    "La campaña debe ser anterior a la campaña actual."
                )
                anio = None
            elif anio < base_year - 15:
                error_campania = (
                    f"La campaña debe estar dentro de las últimas 15 campañas "
                    f"(desde {base_year - 15}/{base_year - 14})."
                )
                anio = None

        cultivo_1 = Cultivo.objects.filter(pk=cultivo_1_id).first()
        cultivo_2 = (
            Cultivo.objects.filter(pk=cultivo_2_id).first()
            if cultivo_2_id
            else None
        )

        if error_campania is not None:
            messages.error(request, error_campania)
        elif cultivo_1 is None:
            messages.error(
                request,
                "Debe indicar la campaña y el cultivo principal.",
            )
        elif cultivo_2_id and cultivo_2 is None:
            messages.error(request, "El segundo cultivo no es válido.")
        elif cultivo_2 is not None and cultivo_2.id == cultivo_1.id:
            messages.error(
                request,
                "El segundo cultivo debe ser distinto del primero.",
            )
        else:
            with transaction.atomic():
                campania, _ = CampaniaHistorica.objects.get_or_create(
                    anio_inicio=anio,
                    defaults={"codigo": f"CH{anio}"},
                )
                HistorialLoteCultivo.objects.filter(
                    lote=lote, campania_historica=campania
                ).delete()
                registros = [
                    HistorialLoteCultivo(
                        lote=lote,
                        cultivo=cultivo_1,
                        campania_historica=campania,
                        presente=True,
                        rendimiento_kg_ha=_parse_rendimiento(rendimiento_1_raw),
                    )
                ]
                if cultivo_2 is not None:
                    registros.append(HistorialLoteCultivo(
                        lote=lote,
                        cultivo=cultivo_2,
                        campania_historica=campania,
                        presente=True,
                        rendimiento_kg_ha=_parse_rendimiento(rendimiento_2_raw),
                    ))
                HistorialLoteCultivo.objects.bulk_create(registros)
            messages.success(
                request,
                f"Historial de {campania.etiqueta} cargado para el lote {lote.codigo}.",
            )

    return lote_list(request)


@login_required(login_url="login")
@require_POST
def lote_historial_delete(request, pk, anio_inicio):
    lote = get_object_or_404(Lote, pk=pk)
    eliminados, _ = HistorialLoteCultivo.objects.filter(
        lote=lote,
        campania_historica__anio_inicio=anio_inicio,
    ).delete()
    if eliminados:
        messages.success(request, f"Historial de la campaña {anio_inicio}/{anio_inicio + 1} eliminado.")
    else:
        messages.error(request, "No se encontró historial para esa campaña.")
    return lote_list(request)


@login_required(login_url="login")
def cultivo_list(request):
    cultivos = (
        Cultivo.objects.annotate(
            costos_totales=Count("costo"),
            costos_pendientes=Count(
                "costo",
                filter=Q(costo__configurado=False),
            ),
        )
        .prefetch_related("rendimientocultivosuelo_set__tipo_suelo")
        .order_by("codigo")
    )
    tipos_suelo = TipoSuelo.objects.all().order_by("codigo")
    base_year = datetime.now().year
    base_date = datetime(base_year, 6, 1)

    for cultivo in cultivos:
        cultivo.es_barbecho = (
            "BARBECHO" in cultivo.codigo.upper()
            or "BARBECHO" in cultivo.nombre.upper()
        )

        # Calcular fechas de inicio y fin asumiendo campaña del 01/06 al 31/05 del año siguiente
        st_date = base_date + timedelta(days=int(cultivo.siembra_inicio) - 1)
        ht_date = base_date + timedelta(days=int(cultivo.siembra_fin) - 1)
        cultivo.siembra_inicio_fecha = st_date.strftime("%d/%m/%Y")
        cultivo.siembra_fin_fecha = ht_date.strftime("%d/%m/%Y")

        # Rendimientos por tipo de suelo
        cultivo.rendimientos = [
            {
                "suelo": r.tipo_suelo.codigo,
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
        }
    )


@login_required(login_url="login")
def cultivo_create(request):
    if request.method == "POST":
        codigo = request.POST.get("codigo")
        nombre = request.POST.get("nombre")
        tipo = request.POST.get("tipo")
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
                    return cultivo_list(request)

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
        else:
            messages.error(request, "Todos los campos son obligatorios.")

    return cultivo_list(request)


@login_required(login_url="login")
def costo_list(request):
    selected_tipo = request.GET.get("tipo", "")
    selected_campania = request.GET.get("campania", "")
    selected_cultivo = request.GET.get("cultivo", "")
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

    costos_generales = costos.exclude(tipo_costo__codigo__in=RENTAL_COST_CODES)
    costos_arrendamiento = costos.filter(tipo_costo__codigo__in=RENTAL_COST_CODES)

    paginator = Paginator(costos_generales, 7)
    page_obj = paginator.get_page(selected_page)
    arrendamiento_paginator = Paginator(costos_arrendamiento, 7)
    arrendamiento_page_obj = arrendamiento_paginator.get_page(
        selected_arrendamiento_page
    )
    _decorate_costos(page_obj.object_list)
    _decorate_costos(arrendamiento_page_obj.object_list)
    
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
        tipo.detalle_mostrar = DETALLES_TIPO_COSTO.get(tipo.codigo, "")
    
    for costo in page_obj.object_list:
        costo.tipo_costo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            costo.tipo_costo.descripcion,
        )
        costo.tipo_costo.detalle_mostrar = DETALLES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            "",
        )

    for costo in arrendamiento_page_obj.object_list:
        costo.tipo_costo.descripcion_mostrar = TRADUCCIONES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            costo.tipo_costo.descripcion,
        )
        costo.tipo_costo.detalle_mostrar = DETALLES_TIPO_COSTO.get(
            costo.tipo_costo.codigo,
            "",
        )
    
    context = {
        "costos": page_obj.object_list,
        "costos_arrendamiento": arrendamiento_page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "arrendamiento_page_obj": arrendamiento_page_obj,
        "arrendamiento_paginator": arrendamiento_paginator,
        "tipos_costo": tipos_costo,
        "campanias": campanias,
        "cultivos": Cultivo.objects.exclude(
            Q(codigo__icontains="BARBECHO") | Q(nombre__icontains="BARBECHO")
        ).order_by("codigo"),
        "selected_tipo": selected_tipo,
        "selected_campania": selected_campania,
        "selected_cultivo": selected_cultivo,
        "selected_page": selected_page,
        "selected_arrendamiento_page": selected_arrendamiento_page,
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
