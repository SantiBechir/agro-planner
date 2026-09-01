import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from core.services.economic_indicators import build_economic_indicators
from accounts.roles import editor_required, has_editor_access
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
import unicodedata

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
        correo = (request.POST.get("email") or "").strip().lower()
        clave = request.POST.get("password")

        try:
            validate_email(correo)
        except ValidationError:
            user = None
        else:
            user = authenticate(request, email=correo, password=clave)
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
@editor_required
@require_POST
def lote_create(request):
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
        suelo_dominante = max(ambientes_data, key=lambda item: item[2])[0]

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
@editor_required
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
@editor_required
@require_POST
def lote_toggle(request, pk):
    lote = get_object_or_404(Lote, pk=pk)
    lote.habilitado = not lote.habilitado
    lote.save(update_fields=["habilitado"])
    estado = "activado" if lote.habilitado else "desactivado"
    messages.success(request, f"Lote {lote.codigo} {estado}.")

    return lote_list(request)


@login_required(login_url="login")
@editor_required
@require_POST
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
@editor_required
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
def cultivo_list(request, form_data=None, open_modal=False):
    cultivos = (
        Cultivo.objects.exclude(
            Q(codigo__icontains="BARBECHO") | Q(nombre__icontains="BARBECHO")
        )
        .annotate(
            costos_totales=Count("costo"),
            costos_pendientes=Count(
                "costo",
                filter=Q(costo__configurado=False),
            ),
        )
        .prefetch_related("rendimientocultivosuelo_set__tipo_suelo")
        .order_by("codigo")
    )
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
        inicio_pct = (int(cultivo.siembra_inicio) / 365) * 100
        fin_pct = ((int(cultivo.siembra_fin) + 1) / 365) * 100
        cultivo.siembra_inicio_pct = f"{inicio_pct:.4f}"
        cultivo.siembra_ancho_pct = f"{fin_pct - inicio_pct:.4f}"

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
            "form_data": form_data,
            "open_modal": open_modal,
        }
    )


@login_required(login_url="login")
@editor_required
@require_POST
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
    selected_suelo = request.GET.get("suelo", "")
    mb_selected_campanias = request.GET.getlist("mb_campania")
    mb_selected_suelos = request.GET.getlist("mb_suelo")
    mb_selected_cultivos = request.GET.getlist("mb_cultivo")
    mb_cultivo_mode = request.GET.get("mb_cultivo_mode", "selected")
    if mb_cultivo_mode not in {"all", "selected"}:
        mb_cultivo_mode = "selected"
    mb_view = request.GET.get("mb_view", "grafico")
    if mb_view not in {"lista", "grafico"}:
        mb_view = "grafico"
    ri_view = request.GET.get("ri_view", "grafico")
    if ri_view not in {"lista", "grafico"}:
        ri_view = "grafico"
    ri_selected_campanias = request.GET.getlist("ri_campania")
    ri_selected_suelos = request.GET.getlist("ri_suelo")
    ri_selected_cultivos = request.GET.getlist("ri_cultivo")
    ri_cultivo_mode = request.GET.get("ri_cultivo_mode", "selected")
    if ri_cultivo_mode not in {"all", "selected"}:
        ri_cultivo_mode = "selected"
    selected_page = request.GET.get("page", "1")
    selected_arrendamiento_page = request.GET.get("arrendamiento_page", "1")
    selected_cultivo_obj = None

    if selected_cultivo:
        selected_cultivo_obj = Cultivo.objects.filter(pk=selected_cultivo).first()

    if request.method == "POST":
        if not has_editor_access(request.user):
            raise PermissionDenied
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
        tipo.detalle_mostrar = DETALLES_TIPO_COSTO.get(tipo.codigo, "")
    
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
    if selected_suelo:
        indicator_data = {
            key: [
                row
                for row in rows
                if str(row["suelo_id"]) == selected_suelo
            ]
            for key, rows in indicator_data.items()
        }
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
    suelos = TipoSuelo.objects.order_by("codigo")
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
        "costos_arrendamiento": arrendamiento_page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "costos_arrendamiento": arrendamiento_page_obj.object_list,
        "arrendamiento_page_obj": arrendamiento_page_obj,
        "arrendamiento_paginator": arrendamiento_paginator,
        "show_costos_generales": show_costos_generales,
        "show_costos_arrendamiento": show_costos_arrendamiento,
        "tipos_costo": tipos_costo,
        "campanias": campanias,
        "cultivos": Cultivo.objects.exclude(
            Q(codigo__icontains="BARBECHO") | Q(nombre__icontains="BARBECHO")
        ).order_by("codigo"),
        "selected_tipo": selected_tipo,
        "selected_campania": selected_campania,
        "selected_cultivo": selected_cultivo,
        "selected_suelo": selected_suelo,
        "selected_page": selected_page,
        "selected_tab": selected_tab,
        "show_standard_indicator_filters": (
            selected_tab == "margenes" and mb_view == "lista"
        ) or (selected_tab == "indiferencia" and ri_view == "lista"),
        "show_costo_cultivo_help": show_costo_cultivo_help,
        "margenes": margenes,
        "mb_selected_campanias": mb_selected_campanias,
        "mb_selected_suelos": mb_selected_suelos,
        "mb_selected_cultivos": mb_selected_cultivos,
        "mb_cultivo_mode": mb_cultivo_mode,
        "mb_view": mb_view,
        "mb_cost_charts": mb_cost_charts,
        "indiferencias": indiferencias,
        "indiferencias_agrupadas": indiferencias_agrupadas,
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
@require_POST
def ejecutar_optimizacion(request):
    nombre = request.POST.get("nombre", f"Planificación {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    planificacion = Planificacion.objects.create(
        nombre=nombre,
        estado=Planificacion.Estado.PENDIENTE
    )

    return redirect("planificacion_status", pk=planificacion.id)


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
