from datetime import datetime, timedelta
from math import isfinite

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Cultivo, LimiteSuperficieCultivoCampania, Planificacion
from core.services.limites import limites_para_usuario
from accounts.roles import editor_required
from django.http import HttpResponse
from django.utils.html import escape
from core.services.planificaciones import solicitar_planificacion


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
def planificacion_list(request):
    planificaciones = Planificacion.objects.filter(usuario=request.user).order_by("-fecha_creacion")
    limites_por_cultivo = {}
    for limite in limites_para_usuario(request.user).select_related("cultivo", "campania").order_by("cultivo__codigo", "campania__orden"):
        if "BARBECHO" in limite.cultivo.codigo.upper() or "BARBECHO" in limite.cultivo.nombre.upper():
            continue
        limites_por_cultivo.setdefault(limite.cultivo_id, {
            "cultivo": limite.cultivo, "limites": [],
        })["limites"].append(limite)
    return render(
        request,
        "core/planificaciones.html",
        {"planificaciones": planificaciones, "limites_por_cultivo": list(limites_por_cultivo.values())},
    )


@login_required(login_url="login")
@require_POST
def ejecutar_optimizacion(request):
    nombre = request.POST.get("nombre", f"Planificación {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    try:
        planificacion = solicitar_planificacion(request.user, nombre=nombre)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("planificacion_list")

    return redirect("planificacion_status", pk=planificacion.id)


def _respuesta_estado(request, pk):
    planificacion = get_object_or_404(Planificacion, pk=pk, usuario=request.user)

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

    if planificacion.estado in (Planificacion.Estado.ERROR, Planificacion.Estado.INFACTIBLE):
        return render(
            request,
            "core/resultados_planificacion.html",
            {
                "error": planificacion.detalle_error or "Ocurrió un error al ejecutar el solver. Verifica la configuración de datos en tu base de datos.",
                "planificacion": planificacion,
            },
        )

    # PENDIENTE o EJECUTANDO: mostrar página de espera con polling
    return render(request, "core/planificacion_status.html", {"planificacion": planificacion})


@login_required(login_url="login")
def planificacion_status(request, pk):
    return _respuesta_estado(request, pk)


@login_required(login_url="login")
def planificacion_status_partial(request, pk):
    """Fragmento de estado para polling HTMX."""
    return _respuesta_estado(request, pk)


@login_required(login_url="login")
@editor_required
@require_POST
def planificacion_limites_update(request, pk):
    """Actualiza los límites del cultivo y avisa al instante si son inviables."""
    cultivo = get_object_or_404(Cultivo, pk=pk)
    limites = list(
        limites_para_usuario(request.user)
        .filter(cultivo=cultivo)
        .select_related("campania")
    )
    mensaje_error = None

    try:
        for limite in limites:
            minimo = float(request.POST[f"min_{limite.pk}"])
            maximo = float(request.POST[f"max_{limite.pk}"])
            if not isfinite(minimo) or not isfinite(maximo):
                raise ValidationError("Los límites deben ser números finitos.")
            if minimo < 0 or maximo < 0:
                raise ValidationError("Los límites de hectáreas no pueden ser negativos.")
            if minimo > maximo:
                raise ValidationError("El mínimo no puede ser mayor que el máximo.")
            limite.min_ha = minimo
            limite.max_ha = maximo

        for limite in limites:
            limite.full_clean()
    except (KeyError, TypeError, ValueError):
        mensaje_error = "Ingresá valores numéricos válidos para todos los límites."
    except ValidationError as exc:
        mensaje_error = " ".join(exc.messages)
    else:
        LimiteSuperficieCultivoCampania.objects.bulk_update(
            limites, ["min_ha", "max_ha"]
        )

    if request.headers.get("HX-Request"):
        if mensaje_error:
            return HttpResponse(
                f'<span class="text-[10px] font-semibold text-red-700">{escape(mensaje_error)}</span>'
            )
        return HttpResponse(
            '<span class="text-[10px] font-semibold text-emerald-700">Guardado automáticamente.</span>'
        )

    if mensaje_error:
        messages.error(request, mensaje_error)
    else:
        messages.success(request, f"Límites de {cultivo.nombre} guardados.")
    return planificacion_list(request)
