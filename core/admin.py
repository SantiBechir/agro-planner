from django.contrib import admin

from .models import (
    Ambiente,
    AsignacionLoteSlot,
    Campania,
    CampaniaHistorica,
    CompatibilidadCultivoSuelo,
    Costo,
    Cultivo,
    HistorialLoteCultivo,
    ImpactoRotacion,
    Lote,
    NivelAntiguedad,
    Planificacion,
    RendimientoCultivoSuelo,
    SecuenciaPermitida,
    SetupCultivo,
    SlotSiembra,
    SueloLote,
    TipoCosto,
    TipoSuelo,
)


@admin.register(TipoSuelo)
class TipoSueloAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre")
    search_fields = ("codigo", "nombre")


@admin.register(Campania)
class CampaniaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "orden", "fecha_inicio", "fecha_fin")
    list_filter = ("orden",)
    search_fields = ("codigo",)


@admin.register(SlotSiembra)
class SlotSiembraAdmin(admin.ModelAdmin):
    list_display = ("codigo", "orden", "campania")
    list_filter = ("campania",)
    search_fields = ("codigo",)


@admin.register(NivelAntiguedad)
class NivelAntiguedadAdmin(admin.ModelAdmin):
    list_display = ("codigo", "orden", "lag", "alfa")
    ordering = ("orden",)


@admin.register(Cultivo)
class CultivoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "tipo",
        "duracion_dias",
        "siembra_inicio",
        "siembra_fin",
        "no_repetir_sin_intermedio",
    )
    list_filter = ("tipo", "no_repetir_sin_intermedio")
    search_fields = ("codigo", "nombre")


class AmbienteInline(admin.TabularInline):
    model = Ambiente
    extra = 0


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "superficie_ha",
        "max_cultivos_principales",
        "max_cultivos_secundarios",
        "tipo_suelo",
        "habilitado",
    )
    list_filter = ("tipo_suelo", "habilitado")
    search_fields = ("codigo", "nombre")
    inlines = [AmbienteInline]


@admin.register(SueloLote)
class SueloLoteAdmin(admin.ModelAdmin):
    list_display = ("lote", "tipo_suelo", "proporcion", "nivel_productividad")
    list_filter = ("tipo_suelo", "nivel_productividad")
    search_fields = ("lote__codigo",)


@admin.register(TipoCosto)
class TipoCostoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "unidad", "es_porcentual")
    search_fields = ("codigo", "descripcion")


@admin.register(Costo)
class CostoAdmin(admin.ModelAdmin):
    list_display = ("cultivo", "tipo_costo", "valor", "campania", "lote")
    list_filter = ("tipo_costo", "campania", "lote")
    search_fields = ("cultivo__codigo", "tipo_costo__codigo")


@admin.register(RendimientoCultivoSuelo)
class RendimientoCultivoSueloAdmin(admin.ModelAdmin):
    list_display = ("cultivo", "tipo_suelo", "valor")
    list_filter = ("tipo_suelo",)
    search_fields = ("cultivo__codigo", "tipo_suelo__codigo")


@admin.register(CompatibilidadCultivoSuelo)
class CompatibilidadCultivoSueloAdmin(admin.ModelAdmin):
    list_display = ("cultivo", "tipo_suelo", "compatible")
    list_filter = ("tipo_suelo", "compatible")
    search_fields = ("cultivo__codigo", "tipo_suelo__codigo")


@admin.register(SetupCultivo)
class SetupCultivoAdmin(admin.ModelAdmin):
    list_display = ("cultivo_previo", "cultivo_siguiente", "dias")
    search_fields = (
        "cultivo_previo__codigo",
        "cultivo_siguiente__codigo",
    )


@admin.register(SecuenciaPermitida)
class SecuenciaPermitidaAdmin(admin.ModelAdmin):
    list_display = ("cultivo_previo", "cultivo_siguiente", "permitido")
    list_filter = ("permitido",)
    search_fields = (
        "cultivo_previo__codigo",
        "cultivo_siguiente__codigo",
    )


@admin.register(ImpactoRotacion)
class ImpactoRotacionAdmin(admin.ModelAdmin):
    list_display = ("cultivo_previo", "cultivo_actual", "valor")
    search_fields = (
        "cultivo_previo__codigo",
        "cultivo_actual__codigo",
    )


@admin.register(CampaniaHistorica)
class CampaniaHistoricaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "anio_inicio")
    ordering = ("-anio_inicio",)
    search_fields = ("codigo",)


@admin.register(HistorialLoteCultivo)
class HistorialLoteCultivoAdmin(admin.ModelAdmin):
    list_display = ("lote", "cultivo", "campania_historica", "presente")
    list_filter = ("campania_historica", "presente")
    search_fields = ("lote__codigo", "cultivo__codigo")


class AsignacionInline(admin.TabularInline):
    model = AsignacionLoteSlot
    extra = 0
    raw_id_fields = ("lote", "cultivo", "slot")


@admin.register(Planificacion)
class PlanificacionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "fecha_creacion", "profit", "ilu", "estado")
    list_filter = ("estado", "fecha_creacion")
    search_fields = ("nombre",)
    inlines = [AsignacionInline]


@admin.register(AsignacionLoteSlot)
class AsignacionLoteSlotAdmin(admin.ModelAdmin):
    list_display = (
        "planificacion",
        "lote",
        "cultivo",
        "slot",
        "dia_siembra",
        "dia_cosecha",
        "profit_value",
    )
    list_filter = ("planificacion", "lote", "cultivo", "slot")
    search_fields = ("planificacion__nombre", "lote__codigo", "cultivo__codigo")

    def profit_value(self, obj):
        if obj.ingreso is not None and obj.costo is not None:
            return obj.ingreso - obj.costo
        return None
    profit_value.short_description = "Profit estimado"
