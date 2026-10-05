"""Alta agronómica y económica de cultivos en una única transacción."""

import unicodedata
from datetime import datetime
from math import isfinite

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.models import (
    AsignacionLoteSlot, Campania, CompatibilidadCultivoSuelo, Costo, Cultivo,
    HistorialLoteCultivo, Lote,
    RendimientoCultivoSuelo, TipoCosto, TipoSuelo,
)
from core.services.authorization import require_editor
from core.services.costos import COMPONENTES_SIEMBRA


def crear_cultivo(actor, *, nombre, tipo, duracion_dias, siembra_inicio_fecha,
                  siembra_fin_fecha, no_repetir, rendimientos):
    require_editor(actor)
    nombre = (nombre or "").strip()
    if len(nombre) > 100:
        raise ValidationError("El nombre del cultivo debe tener hasta 100 caracteres.")
    codigo = (
        unicodedata.normalize("NFD", nombre).encode("ascii", "ignore")
        .decode("utf-8").upper().strip()
    ) if nombre else ""
    if nombre and Cultivo.objects.filter(nombre__iexact=nombre.strip()).exists():
        raise ValidationError(f"Ya existe un cultivo con el nombre '{nombre}'.")
    if Cultivo.objects.filter(codigo=codigo).exists():
        raise ValidationError(f"Ya existe un cultivo con el código '{codigo}'.")
    if not all((codigo, nombre, tipo, duracion_dias, siembra_inicio_fecha, siembra_fin_fecha)):
        raise ValidationError("Todos los campos son obligatorios.")
    if len(codigo) > 50 or tipo not in Cultivo.Tipo.values:
        raise ValidationError("El tipo de cultivo o la longitud del nombre no es válido.")
    try:
        base_date = datetime(datetime.now().year, 6, 1)
        inicio_dt = datetime.strptime(siembra_inicio_fecha, "%Y-%m-%d")
        fin_dt = datetime.strptime(siembra_fin_fecha, "%Y-%m-%d")
        siembra_inicio = (inicio_dt - base_date).days + 1
        siembra_fin = (fin_dt - base_date).days + 1
    except (TypeError, ValueError) as exc:
        raise ValidationError("Ingrese fechas de siembra válidas.") from exc
    if siembra_fin < siembra_inicio:
        raise ValidationError("La fecha de fin de siembra no puede ser anterior a la de inicio.")
    try:
        duracion = int(duracion_dias)
        if not 1 <= duracion <= 365:
            raise ValueError
        rendimientos = {key: float(value) for key, value in rendimientos.items()}
        if any(not isfinite(value) or value < 0 for value in rendimientos.values()):
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError("Ingrese una duración de 1 a 365 días y rendimientos válidos mayores o iguales a cero.") from exc
    try:
        with transaction.atomic():
            cultivo = Cultivo.objects.create(
                codigo=codigo.strip().upper(),
                nombre=nombre.strip(),
                creado_por=actor,
                tipo=tipo,
                duracion_dias=duracion,
                siembra_inicio=siembra_inicio,
                siembra_fin=siembra_fin,
                no_repetir_sin_intermedio=no_repetir,
                habilitado_optimizacion=False,
            )

            # Crear rendimientos y compatibilidades por cada tipo de suelo
            tipos_suelo = TipoSuelo.objects.all()
            for suelo in tipos_suelo:
                rend_val = rendimientos.get(suelo.id, 0.0)
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

            tipos_costo = {
                tipo.codigo: tipo
                for tipo in TipoCosto.objects.filter(
                    codigo__in=[
                        "fsp", *COMPONENTES_SIEMBRA, "hc", "frc", "vr", "tf",
                        "scp", "cp", "st", "cst", "clt",
                    ]
                )
            }
            campanias = list(Campania.objects.order_by("orden"))
            lotes = list(Lote.objects.order_by("codigo"))
            costos = []

            for codigo_tipo in ("tf", "scp", "st"):
                if codigo_tipo in tipos_costo:
                    costos.append(Costo(
                        cultivo=cultivo,
                        tipo_costo=tipos_costo[codigo_tipo],
                        valor=0,
                        configurado=False,
                    ))

            for codigo_tipo in ("fsp", *COMPONENTES_SIEMBRA, "hc", "cp", "cst", "clt"):
                if codigo_tipo in tipos_costo:
                    costos.extend(
                        Costo(
                            cultivo=cultivo,
                            tipo_costo=tipos_costo[codigo_tipo],
                            campania=campania,
                            valor=0,
                            configurado=False,
                        )
                        for campania in campanias
                    )

            for codigo_tipo in ("frc", "vr"):
                if codigo_tipo in tipos_costo:
                    costos.extend(
                        Costo(
                            cultivo=cultivo,
                            tipo_costo=tipos_costo[codigo_tipo],
                            campania=campania,
                            lote=lote,
                            valor=0,
                            configurado=False,
                        )
                        for campania in campanias
                        for lote in lotes
                    )

            Costo.objects.bulk_create(costos)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Los datos del cultivo no son válidos.") from exc
    return cultivo


def eliminar_cultivo(actor, *, cultivo_id):
    require_editor(actor)
    with transaction.atomic():
        cultivo = (
            Cultivo.objects.select_for_update()
            .filter(pk=cultivo_id, creado_por=actor)
            .first()
        )
        if cultivo is None:
            raise PermissionDenied("Solo podés eliminar los cultivos que agregaste.")
        if (
            HistorialLoteCultivo.objects.filter(cultivo=cultivo).exists()
            or AsignacionLoteSlot.objects.filter(cultivo=cultivo).exists()
        ):
            raise ValidationError(
                "No se puede eliminar este cultivo porque figura en el historial "
                "de un lote o en una planificación guardada."
            )
        nombre = cultivo.nombre
        cultivo.delete()
    return nombre
