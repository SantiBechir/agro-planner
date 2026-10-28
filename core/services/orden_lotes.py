"""Orden numérico de códigos J1, J2, …, J10, seguido de códigos libres."""
import re

from django.db.models import BigIntegerField, Case, IntegerField, Value, When
from django.db.models.functions import Cast, Substr


def clave_codigo_lote(codigo):
    numero = re.fullmatch(r"J([0-9]+)", codigo)
    return (0, int(numero[1]), codigo) if numero else (1, 0, codigo)


def ordenar_por_codigo_lote(queryset, *, campo="codigo", antes=()):
    """Ordena en SQL antes de paginar; admite relaciones como lote__codigo."""
    es_numerico = {f"{campo}__regex": r"^J[0-9]+$"}
    return queryset.annotate(
        _lote_tipo=Case(When(**es_numerico, then=Value(0)), default=Value(1), output_field=IntegerField()),
        _lote_numero=Case(
            When(**es_numerico, then=Cast(Substr(campo, 2), BigIntegerField())),
            default=Value(0), output_field=BigIntegerField(),
        ),
    ).order_by(*antes, "_lote_tipo", "_lote_numero", campo, "pk")
