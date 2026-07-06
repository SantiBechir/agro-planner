from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.models import Lote, Cultivo, Planificacion, AsignacionLoteSlot
from datetime import datetime, timedelta
import math


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
    return render(request, "core/lotes_list.html", {"lotes": lotes})


@login_required(login_url="login")
def cultivo_list(request):
    cultivos = Cultivo.objects.all().order_by("codigo")
    return render(request, "core/cultivos_list.html", {"cultivos": cultivos})


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

        # Crear planificación pendiente; el worker la procesará en segundo plano
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
