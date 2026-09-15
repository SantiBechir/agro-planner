"""Alta agronómica y económica de cultivos en una única transacción."""

import unicodedata
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import (
    Campania, CompatibilidadCultivoSuelo, Costo, Cultivo, Lote,
    RendimientoCultivoSuelo, TipoCosto, TipoSuelo,
)
from core.services.authorization import require_editor
from core.services.costos import COMPONENTES_SIEMBRA


def crear_cultivo(actor, *, nombre, tipo, duracion_dias, siembra_inicio_fecha,
                  siembra_fin_fecha, no_repetir, rendimientos):
    require_editor(actor)
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
    try:
        base_date = datetime(datetime.now().year, 6, 1)
        inicio_dt = datetime.strptime(siembra_inicio_fecha, "%Y-%m-%d")
        fin_dt = datetime.strptime(siembra_fin_fecha, "%Y-%m-%d")
        siembra_inicio = (inicio_dt - base_date).days + 1
        siembra_fin = (fin_dt - base_date).days + 1
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Error al crear cultivo: {exc}") from exc
    if siembra_fin < siembra_inicio:
        raise ValidationError("La fecha de fin de siembra no puede ser anterior a la de inicio.")
    try:
        with transaction.atomic():
            cultivo = Cultivo.objects.create(
                codigo=codigo.strip().upper(),
                nombre=nombre.strip(),
                tipo=tipo,
                duracion_dias=int(duracion_dias),
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
        raise ValidationError(f"Error al crear cultivo: {exc}") from exc
    return cultivo
