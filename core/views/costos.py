from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render

from core.presentation import economia
from core.services import costos
from core.services.economic_indicators import build_economic_indicators


def _filtros_costos(params):
    selected_tab = params.get("tab", "detalle")
    if selected_tab not in {"margenes", "indiferencia", "detalle"}:
        selected_tab = "detalle"
    selected_tipo = params.get("tipo", "")
    selected_campania = params.get("campania", "")
    selected_cultivo = params.get("cultivo", "")
    selected_suelo = params.get("suelo", "")
    mb_selected_campanias = params.getlist("mb_campania")
    mb_selected_suelos = params.getlist("mb_suelo")
    mb_selected_cultivos = params.getlist("mb_cultivo")
    mb_cultivo_mode = params.get("mb_cultivo_mode", "selected")
    if mb_cultivo_mode not in {"all", "selected"}:
        mb_cultivo_mode = "selected"
    mb_view = params.get("mb_view", "grafico")
    if mb_view not in {"lista", "grafico"}:
        mb_view = "grafico"
    ri_view = params.get("ri_view", "grafico")
    if ri_view not in {"lista", "grafico"}:
        ri_view = "grafico"
    ri_selected_campanias = params.getlist("ri_campania")
    ri_selected_suelos = params.getlist("ri_suelo")
    ri_selected_cultivos = params.getlist("ri_cultivo")
    ri_cultivo_mode = params.get("ri_cultivo_mode", "selected")
    if ri_cultivo_mode not in {"all", "selected"}:
        ri_cultivo_mode = "selected"
    selected_page = params.get("page", "1")
    selected_arrendamiento_page = params.get("arrendamiento_page", "1")
    return {
        "selected_tab": selected_tab,
        "selected_tipo": selected_tipo,
        "selected_campania": selected_campania,
        "selected_cultivo": selected_cultivo,
        "selected_suelo": selected_suelo,
        "mb_selected_campanias": mb_selected_campanias,
        "mb_selected_suelos": mb_selected_suelos,
        "mb_selected_cultivos": mb_selected_cultivos,
        "mb_cultivo_mode": mb_cultivo_mode,
        "mb_view": mb_view,
        "ri_view": ri_view,
        "ri_selected_campanias": ri_selected_campanias,
        "ri_selected_suelos": ri_selected_suelos,
        "ri_selected_cultivos": ri_selected_cultivos,
        "ri_cultivo_mode": ri_cultivo_mode,
        "selected_page": selected_page,
        "selected_arrendamiento_page": selected_arrendamiento_page,
    }


def _actualizar_costos(request, cultivo_id):
    valores = {
        key.removeprefix("costo_"): value.strip().replace(",", ".")
        for key, value in request.POST.items() if key.startswith("costo_")
    }
    try:
        resultado = costos.actualizar_costos(
            request.user, valores, cultivo_id=cultivo_id,
            habilitar=request.POST.get("action") == "enable",
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return
    if resultado.pendientes:
        messages.error(request, f"Todavía faltan revisar {resultado.pendientes} valores antes de habilitar el cultivo.")
    elif resultado.cultivo_habilitado is not None:
        messages.success(request, f"Cultivo {resultado.cultivo_habilitado.codigo} habilitado para optimización.")
    messages.success(request, f"Se actualizaron {resultado.modificados} valores de precios y costos.")
    return resultado


def _contexto_costos(filtros, cultivo):
    listado = costos.consultar_costos(**{
        key: filtros[key] for key in (
            "selected_tipo", "selected_campania", "selected_cultivo",
            "selected_page", "selected_arrendamiento_page",
        )
    })
    tipo_codigo = listado.pop("tipo_seleccionado_codigo")
    catalogos = costos.consultar_catalogos()
    economia.decorar_catalogos(
        listado["page_obj"], listado["arrendamiento_page_obj"],
        catalogos["campanias"], catalogos["tipos_costo"], costos.anio_base_costos(),
    )
    indicadores = economia.filtrar_indicadores(
        build_economic_indicators(), **{key: filtros[key] for key in (
            "selected_campania", "selected_cultivo", "selected_suelo",
        )}
    )
    return {
        **listado,
        **catalogos,
        **{key: value for key, value in filtros.items() if key != "selected_arrendamiento_page"},
        **economia.preparar_tablas(indicadores),
        **economia.preparar_grafico_indiferencia(indicadores, **{
            key: filtros[key] for key in (
                "ri_selected_campanias", "ri_selected_suelos", "ri_selected_cultivos", "ri_cultivo_mode",
            )
        }),
        "mb_cost_charts": economia.preparar_graficos_margen(indicadores["margins"], **{
            key: filtros[key] for key in (
                "mb_selected_campanias", "mb_selected_suelos", "mb_selected_cultivos", "mb_cultivo_mode",
            )
        }),
        "costos": listado["page_obj"].object_list,
        "costos_arrendamiento": listado["arrendamiento_page_obj"].object_list,
        "show_standard_indicator_filters": (
            filtros["selected_tab"] == "margenes" and filtros["mb_view"] == "lista"
        ) or (filtros["selected_tab"] == "indiferencia" and filtros["ri_view"] == "lista"),
        "show_costo_cultivo_help": tipo_codigo in costos.COMPONENTES_SIEMBRA,
        "totales_siembra": costos.consultar_totales_siembra(
            tipo_seleccionado_codigo=tipo_codigo,
            selected_campania=filtros["selected_campania"],
            selected_cultivo=filtros["selected_cultivo"],
        ),
        "selected_cultivo_obj": cultivo,
        "costos_pendientes": costos.contar_costos_pendientes(cultivo),
    }


@login_required(login_url="login")
def costo_list(request):
    filtros = _filtros_costos(request.GET)
    cultivo = costos.obtener_cultivo(filtros["selected_cultivo"])
    if request.method == "POST":
        resultado = _actualizar_costos(request, cultivo.pk if cultivo else None)
        if resultado is not None and resultado.cultivo_habilitado is not None:
            cultivo = resultado.cultivo_habilitado
    return render(request, "core/costos_list.html", _contexto_costos(filtros, cultivo))
