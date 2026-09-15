from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.roles import editor_required
from core.models import Cultivo, TipoSuelo
from core.services.cultivos import crear_cultivo


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
    form_data = request.POST.dict()
    form_data["no_repetir_sin_intermedio"] = request.POST.get("no_repetir_sin_intermedio") == "on"
    try:
        cultivo = crear_cultivo(
            request.user, nombre=request.POST.get("nombre"), tipo=request.POST.get("tipo"),
            duracion_dias=request.POST.get("duracion_dias"),
            siembra_inicio_fecha=request.POST.get("siembra_inicio_fecha"),
            siembra_fin_fecha=request.POST.get("siembra_fin_fecha"),
            no_repetir=form_data["no_repetir_sin_intermedio"],
            rendimientos={suelo_id: request.POST.get(f"rendimiento_{suelo_id}", 0.0)
                          for suelo_id in TipoSuelo.objects.values_list("id", flat=True)},
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return cultivo_list(request, form_data=form_data, open_modal=True)
    except Exception as exc:
        messages.error(request, f"Error al crear cultivo: {exc}")
        return cultivo_list(request, form_data=form_data, open_modal=True)
    messages.success(request, f"Cultivo {cultivo.codigo} creado. Completa sus precios y costos antes de habilitarlo.")
    return cultivo_list(request)
