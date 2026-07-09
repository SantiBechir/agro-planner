from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.models import (
    Lote,
    Cultivo,
    Planificacion,
    AsignacionLoteSlot,
    TipoSuelo,
    RendimientoCultivoSuelo,
    CompatibilidadCultivoSuelo,
)
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
def cultivo_list(request):
    cultivos = Cultivo.objects.prefetch_related("rendimientocultivosuelo_set__tipo_suelo").order_by("codigo")
    tipos_suelo = TipoSuelo.objects.all().order_by("codigo")
    base_year = datetime.now().year
    base_date = datetime(base_year, 6, 1)

    for cultivo in cultivos:
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
                        no_repetir_sin_intermedio=no_repetir
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
                messages.success(request, f"Cultivo {codigo} creado con éxito.")
            except Exception as e:
                messages.error(request, f"Error al crear cultivo: {str(e)}")
        else:
            messages.error(request, "Todos los campos son obligatorios.")

    return cultivo_list(request)


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