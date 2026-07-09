from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.models import Lote, Cultivo, Planificacion, AsignacionLoteSlot, HistorialLoteCultivo
from core.services.solver import run_optimization
from datetime import datetime, timedelta
import math

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
    for lote in lotes:
        lote.historial = (
            HistorialLoteCultivo.objects.filter(
                lote=lote,
                presente=True,
            )
            .select_related("cultivo", "campania_historica")
            .order_by("-campania_historica__orden")[:3]
        )

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
        
        # Crear planificación pendiente
        planificacion = Planificacion.objects.create(
            nombre=nombre,
            estado=Planificacion.Estado.PENDIENTE
        )

        # Ejecutar solver (sincrónicamente por ahora para HTMX)
        success = run_optimization(planificacion.id)
        
        planificacion.refresh_from_db()

        if success and planificacion.estado == Planificacion.Estado.COMPLETADO:
            asignaciones = planificacion.asignaciones.select_related("lote", "cultivo", "slot").order_by("lote__codigo", "slot__orden")
            
            # Generar datos para Gantt
            gantt_data = []
            base_year = datetime.now().year
            base_date = datetime(base_year, 6, 1)

            # Eje Y: Lotes
            lotes_list = sorted(list(set(asig.lote.codigo for asig in asignaciones)))
            y_pos = {lote_cod: idx for idx, lote_cod in enumerate(lotes_list)}

            # Eje X: Convertir días de siembra/cosecha a fechas reales
            for asig in asignaciones:
                # Omitir barbecho o asignaciones vacías en el gráfico si es necesario
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

            context = {
                "planificacion": planificacion,
                "gantt_data": gantt_data,
                "lotes_list": lotes_list,
            }
            return render(request, "core/resultados_planificacion.html", context)
        else:
            return render(
                request,
                "core/resultados_planificacion.html",
                {"error": "Ocurrió un error al ejecutar el solver. Verifica la configuración de datos en tu base de datos."},
            )

    return redirect("planificacion_list")