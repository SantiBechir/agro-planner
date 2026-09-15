import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from accounts.roles import editor_required
from core.models import CampaniaHistorica, Cultivo, HistorialLoteCultivo, Lote, TipoSuelo
from core.services import historial, lotes


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


def _raw_ambientes(request):
    indices = sorted({
        int(key.rsplit("_", 1)[1]) for key in request.POST
        if re.fullmatch(r"(suelo|rendimiento|ha)_\d+", key)
    })
    return [
        {"suelo": (request.POST.get(f"suelo_{i}") or "").strip(),
         "rendimiento": (request.POST.get(f"rendimiento_{i}") or "").strip(),
         "ha": (request.POST.get(f"ha_{i}") or "").strip()}
        for i in indices
    ]


def _ambientes_data(raw):
    return [(a["suelo"], a["rendimiento"], a["ha"]) for a in raw]


@login_required(login_url="login")
@editor_required
@require_POST
def lote_create(request):
    nombre = (request.POST.get("nombre") or "").strip()
    raw = _raw_ambientes(request)
    try:
        lote = lotes.crear_lote(request.user, nombre=nombre, ambientes=_ambientes_data(raw))
    except ValidationError as exc:
        return lote_list(request, create_error=exc.messages[0], create_nombre=nombre,
                         create_ambientes=raw)
    messages.success(request, f"Lote {lote.codigo} ({nombre}) creado con éxito.")
    return lote_list(request)


@login_required(login_url="login")
@editor_required
@require_POST
def lote_update(request, pk):
    get_object_or_404(Lote, pk=pk)
    try:
        lote = lotes.actualizar_lote(
            request.user, pk, nombre=(request.POST.get("nombre") or "").strip(),
            ambientes=_ambientes_data(_raw_ambientes(request)),
            habilitado=request.POST.get("habilitado") == "1",
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, f"Lote {lote.codigo} actualizado con éxito.")
    return lote_list(request)


@login_required(login_url="login")
@editor_required
@require_POST
def lote_toggle(request, pk):
    get_object_or_404(Lote, pk=pk)
    lote = lotes.alternar_lote(request.user, pk)
    estado = "activado" if lote.habilitado else "desactivado"
    messages.success(request, f"Lote {lote.codigo} {estado}.")
    return lote_list(request)


@login_required(login_url="login")
@editor_required
@require_POST
def lote_historial_add(request, pk):
    get_object_or_404(Lote, pk=pk)
    try:
        campania, lote = historial.cargar_historial(
            request.user, pk,
            anio_inicio=(request.POST.get("anio_inicio") or "").strip(),
            cultivo_1_id=request.POST.get("cultivo_1"),
            cultivo_2_id=(request.POST.get("cultivo_2") or "").strip(),
            rendimiento_1=(request.POST.get("rendimiento_1") or "").strip(),
            rendimiento_2=(request.POST.get("rendimiento_2") or "").strip(),
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, f"Historial de {campania.etiqueta} cargado para el lote {lote.codigo}.")
    return lote_list(request)


@login_required(login_url="login")
@editor_required
@require_POST
def lote_historial_delete(request, pk, anio_inicio):
    get_object_or_404(Lote, pk=pk)
    eliminados = historial.eliminar_historial(request.user, pk, anio_inicio=anio_inicio)
    if eliminados:
        messages.success(request, f"Historial de la campaña {anio_inicio}/{anio_inicio + 1} eliminado.")
    else:
        messages.error(request, "No se encontró historial para esa campaña.")
    return lote_list(request)
