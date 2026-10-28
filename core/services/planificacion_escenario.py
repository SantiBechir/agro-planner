"""Selección de una corrida y copia JSON de sus entradas, independiente del catálogo."""
from datetime import date
from math import isfinite

from django.core.exceptions import ValidationError
from django.db.models import Q

from core.models import Campania, CampaniaHistorica, Cultivo, Lote, SlotSiembra
from core.services.orden_lotes import ordenar_por_codigo_lote


BARBECHO = Q(codigo__iexact="BARBECHO")


def opciones_planificacion(usuario):
    return (
        list(Campania.objects.order_by("orden").prefetch_related("slots")),
        list(Cultivo.objects.filter(
            configuraciones_usuario__usuario=usuario,
            configuraciones_usuario__habilitado_optimizacion=True,
        ).exclude(BARBECHO).order_by("nombre")),
        list(ordenar_por_codigo_lote(Lote.objects.filter(usuario=usuario, habilitado=True))),
    )


def validar_seleccion(usuario, seleccion):
    """Normaliza datos no confiables; nunca modifica habilitaciones ni límites."""
    campanias, cultivos, lotes = opciones_planificacion(usuario)
    try:
        cantidad = int(seleccion["cantidad_campanias"])
        cultivo_ids = {int(pk) for pk in seleccion["cultivos"]}
        lote_ids = {int(pk) for pk in seleccion["lotes"]}
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValidationError("Seleccioná campañas, cultivos y lotes válidos.")
    if not 1 <= cantidad <= len(campanias):
        raise ValidationError("La cantidad de campañas está fuera del rango disponible.")
    campanias = campanias[:cantidad]
    if any(not campania.slots.all() for campania in campanias):
        raise ValidationError("Todas las campañas seleccionadas deben tener turnos de siembra.")
    if not cultivo_ids or not cultivo_ids <= {obj.pk for obj in cultivos}:
        raise ValidationError("Seleccioná al menos un cultivo habilitado válido, además del barbecho.")
    if not lote_ids or not lote_ids <= {obj.pk for obj in lotes}:
        raise ValidationError("Seleccioná al menos un lote propio habilitado válido.")
    if any(not isfinite(obj.superficie_ha) or obj.superficie_ha <= 0
           for obj in lotes if obj.pk in lote_ids):
        raise ValidationError("Los lotes seleccionados deben tener una superficie positiva y finita.")
    barbecho = Cultivo.objects.filter(BARBECHO).first()
    if barbecho is None:
        raise ValidationError("Falta el barbecho del modelo. Inicializá el modelo antes de ejecutar.")
    limites = []
    enviados = seleccion.get("limites", {})
    for cultivo_id in sorted(cultivo_ids):
        for campania in campanias:
            try:
                valores = enviados[f"{cultivo_id}_{campania.pk}"]
                minimo, maximo = float(valores["min"]), float(valores["max"])
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ValidationError("Ingresá ambos límites numéricos para cada cultivo y campaña incluidos.")
            if not isfinite(minimo) or not isfinite(maximo) or minimo < 0 or maximo < minimo:
                raise ValidationError("Los límites deben ser finitos, no negativos y el mínimo no puede superar al máximo.")
            limites.append({"cultivo_id": cultivo_id, "campania_id": campania.pk,
                            "min_ha": minimo, "max_ha": maximo})
    return {"version": 1, "campanias": [obj.pk for obj in campanias],
            "cultivos": sorted(cultivo_ids), "lotes": sorted(lote_ids),
            "barbecho_id": barbecho.pk, "limites": limites}


def congelar_entradas(data, usuario):
    """Las claves de tuplas se escriben como listas en pares clave/valor JSON."""
    parametros = {
        nombre: {"pares": [[list(k) if isinstance(k, tuple) else k, v]
                            for k, v in valor.items()]} if isinstance(valor, dict) else valor
        for nombre, valor in data.items()
    }
    campanias = list(Campania.objects.filter(codigo__in=data["c"]).order_by("orden"))
    cultivos = list(Cultivo.objects.filter(codigo__in=data["i"]).order_by("nombre"))
    lotes = list(ordenar_por_codigo_lote(Lote.objects.filter(usuario=usuario, codigo__in=data["j"])))
    fecha_base = (campanias[0].fecha_inicio if campanias else None) or date(CampaniaHistorica.anio_base_actual(), 6, 1)
    etiquetas = {
        "fecha_base": fecha_base.isoformat(),
        "campanias": [{"id": obj.pk, "codigo": obj.codigo,
                       "fecha_inicio": obj.fecha_inicio.isoformat() if obj.fecha_inicio else "",
                       "fecha_fin": obj.fecha_fin.isoformat() if obj.fecha_fin else ""} for obj in campanias],
        "cultivos": [{"id": obj.pk, "codigo": obj.codigo, "nombre": obj.nombre,
                      "barbecho": obj.codigo.upper() == "BARBECHO"} for obj in cultivos],
        "lotes": [{"id": obj.pk, "codigo": obj.codigo, "nombre": obj.nombre,
                   "superficie_ha": data["ha"][obj.codigo]} for obj in lotes],
        "slots": list(SlotSiembra.objects.filter(codigo__in=data["t"]).values("id", "codigo")),
        "limites": [{"cultivo": obj.nombre, "campania": camp,
                     "min_ha": data["minha_dict"].get((obj.codigo, camp), 0),
                     "max_ha": data["maxha_dict"].get((obj.codigo, camp),
                         sum(data["ha"].values()) * len(data["tc_dict"][camp]))}
                    for obj in cultivos if obj.codigo.upper() != "BARBECHO" for camp in data["c"]],
    }
    return {"version": 1, "parametros": parametros, "etiquetas": etiquetas}


def restaurar_entradas(snapshot):
    if snapshot.get("version") != 1:
        raise ValueError("Versión de datos de ejecución no compatible.")
    return {
        nombre: {(tuple(k) if isinstance(k, list) else k): v for k, v in valor["pares"]}
        if isinstance(valor, dict) else valor
        for nombre, valor in snapshot["parametros"].items()
    }
