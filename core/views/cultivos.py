from datetime import datetime, timedelta
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import escape
from django.views.decorators.http import require_POST

from accounts.roles import editor_required
from core.models import Cultivo, LimiteSuperficieCultivoCampania, TipoSuelo
from core.services.cultivos import crear_cultivo, eliminar_cultivo
from core.services.limites import limites_para_usuario

logger = logging.getLogger(__name__)


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
    limites_por_cultivo = {}
    for limite in limites_para_usuario(request.user).select_related("campania"):
        limites_por_cultivo.setdefault(limite.cultivo_id, []).append(limite)
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
        # Rendimientos por tipo de suelo
        cultivo.limites_personales = limites_por_cultivo.get(cultivo.id, [])
        cultivo.rendimientos = [
            {
                "suelo": r.tipo_suelo.nombre or r.tipo_suelo.codigo,
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
    except Exception:
        logger.exception("Error interno al crear un cultivo")
        messages.error(request, "No se pudo crear el cultivo. Intentá nuevamente o contactá al administrador.")
        return cultivo_list(request, form_data=form_data, open_modal=True)
    messages.success(request, f"Cultivo {cultivo.codigo} creado. Completa sus precios y costos antes de habilitarlo.")
    return cultivo_list(request)


@login_required(login_url="login")
@editor_required
@require_POST
def cultivo_delete(request, pk):
    try:
        nombre = eliminar_cultivo(request.user, cultivo_id=pk)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, f"Cultivo {nombre} eliminado.")
    return cultivo_list(request)

@login_required(login_url="login")
@require_POST
def cultivo_limites_update(request, pk):
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
    return cultivo_list(request)