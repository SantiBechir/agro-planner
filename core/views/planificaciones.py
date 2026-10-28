from datetime import datetime, timedelta
from math import isfinite
import json

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_GET

from core.models import Cultivo, LimiteSuperficieCultivoCampania, Planificacion
from core.services.limites import limites_para_usuario
from accounts.roles import editor_required
from django.http import HttpResponse
from django.utils.html import escape
from core.services.planificaciones import solicitar_planificacion
from core.services.planificacion_escenario import opciones_planificacion
from core.services.orden_lotes import clave_codigo_lote


def _build_gantt_data(asignaciones, snapshot=None):
    """Construye los datos del Gantt a partir de asignaciones de una planificación."""
    base_year = datetime.now().year
    base_date = datetime(base_year, 6, 1)
    etiquetas = (snapshot or {}).get("etiquetas", {})
    if etiquetas.get("fecha_base"):
        base_date = datetime.fromisoformat(etiquetas["fecha_base"])
    lotes_guardados = {obj["id"]: obj["codigo"] for obj in etiquetas.get("lotes", [])}
    cultivos_guardados = {obj["id"]: obj["codigo"] for obj in etiquetas.get("cultivos", [])}
    slots_guardados = {obj["id"]: obj["codigo"] for obj in etiquetas.get("slots", [])}

    asignaciones = sorted(asignaciones, key=lambda asig: (
        clave_codigo_lote(lotes_guardados.get(asig.lote_id, asig.lote.codigo)), asig.slot.orden,
    ))
    lotes_list = sorted({lotes_guardados.get(asig.lote_id, asig.lote.codigo) for asig in asignaciones}, key=clave_codigo_lote)
    y_pos = {lote_cod: idx for idx, lote_cod in enumerate(lotes_list)}

    gantt_data = []
    for asig in asignaciones:
        lote_codigo = lotes_guardados.get(asig.lote_id, asig.lote.codigo)
        st_date = base_date + timedelta(days=int(asig.dia_siembra) - 1)
        ht_date = base_date + timedelta(days=int(asig.dia_cosecha) - 1)
        duration = (ht_date - st_date).days

        gantt_data.append({
            "lote": lote_codigo,
            "y_pos": y_pos[lote_codigo],
            "cultivo": cultivos_guardados.get(asig.cultivo_id, asig.cultivo.codigo),
            "slot": slots_guardados.get(asig.slot_id, asig.slot.codigo),
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
    return render(
        request,
        "core/planificaciones.html",
        {"planificaciones": planificaciones},
    )


def _configuracion_response(request, errores=None):
    campanias, cultivos, lotes = opciones_planificacion(request.user)
    enviado = request.method == "POST"
    seleccion_cultivos = request.POST.getlist("cultivos") if enviado else [str(obj.pk) for obj in cultivos]
    seleccion_lotes = request.POST.getlist("lotes") if enviado else [str(obj.pk) for obj in lotes]
    cantidad = request.POST.get("cantidad_campanias", "") if enviado else len(campanias)
    try:
        cantidad_estado = int(cantidad)
    except (ValueError, TypeError):
        cantidad_estado = 0
    limites = {(obj.cultivo_id, obj.campania_id): obj for obj in
               LimiteSuperficieCultivoCampania.objects.filter(usuario=request.user)}
    filas = []
    for cultivo in cultivos:
        celdas = []
        for indice, campania in enumerate(campanias):
            limite = limites.get((cultivo.pk, campania.pk))
            key = f"{cultivo.pk}_{campania.pk}"
            minimo = limite.min_ha if limite else 0
            maximo = limite.max_ha if limite else 500
            celdas.append({"campania": campania, "indice": indice, "key": key,
                          "min": request.POST.get(f"min_{key}", minimo) if enviado else minimo,
                          "max": request.POST.get(f"max_{key}", maximo) if enviado else maximo})
        filas.append({"cultivo": cultivo, "celdas": celdas})
    estado = {"cultivos": seleccion_cultivos, "lotes": seleccion_lotes, "cantidad": cantidad_estado,
              "todosCultivos": [str(obj.pk) for obj in cultivos], "todosLotes": [str(obj.pk) for obj in lotes],
              "areas": {str(obj.pk): obj.superficie_ha for obj in lotes}}
    return render(request, "core/planificacion_configuracion.html", {
        "campanias": campanias, "cultivos": cultivos, "lotes": lotes, "filas": filas,
        "cantidad": cantidad, "configuracion_json": json.dumps(estado), "errores": errores,
        "nombre": request.POST.get("nombre", "") if enviado else f"Planificación Campaña {datetime.now().year}",
    })


@login_required(login_url="login")
@require_GET
def planificacion_configuracion(request):
    return _configuracion_response(request)


@login_required(login_url="login")
@require_GET
def planificacion_datos(request, pk):
    planificacion = get_object_or_404(Planificacion, pk=pk, usuario=request.user)
    datos = (planificacion.datos_entrada or {}).get("etiquetas")
    if datos:
        datos = {
            **datos,
            "lotes": sorted(datos.get("lotes", []), key=lambda lote: clave_codigo_lote(lote["codigo"])),
            "cultivos": [cultivo for cultivo in datos.get("cultivos", [])
                         if not cultivo.get("barbecho") and cultivo.get("codigo", "").upper() != "BARBECHO"],
        }
    return render(request, "core/planificacion_datos.html", {
        "planificacion": planificacion, "datos": datos,
        "tab_datos": True,
    })


@login_required(login_url="login")
@require_POST
def ejecutar_optimizacion(request):
    nombre = request.POST.get("nombre", "")

    try:
        limites = {}
        for key in request.POST:
            if key.startswith("min_"):
                limites[key[4:]] = {"min": request.POST[key], "max": request.POST.get(f"max_{key[4:]}")}
        planificacion = solicitar_planificacion(request.user, nombre=nombre, seleccion={
            "cantidad_campanias": request.POST.get("cantidad_campanias"),
            "cultivos": request.POST.getlist("cultivos"), "lotes": request.POST.getlist("lotes"),
            "limites": limites,
        })
    except ValidationError as exc:
        return _configuracion_response(request, errores=exc.messages)

    return redirect("planificacion_status", pk=planificacion.id)


def _respuesta_estado(request, pk):
    planificacion = get_object_or_404(Planificacion, pk=pk, usuario=request.user)

    if planificacion.estado == Planificacion.Estado.COMPLETADO:
        asignaciones = planificacion.asignaciones.select_related(
            "lote", "cultivo", "slot"
        ).order_by("lote__codigo", "slot__orden")
        gantt_data, lotes_list = _build_gantt_data(asignaciones, planificacion.datos_entrada)
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
