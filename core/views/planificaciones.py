from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Planificacion
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

    planificacion = solicitar_planificacion(request.user, nombre=nombre)

    return redirect("planificacion_status", pk=planificacion.id)


def _respuesta_estado(request, pk):
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
def planificacion_status(request, pk):
    return _respuesta_estado(request, pk)


@login_required(login_url="login")
def planificacion_status_partial(request, pk):
    """Fragmento de estado para polling HTMX."""
    return _respuesta_estado(request, pk)
