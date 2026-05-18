from django.contrib import admin

from .models import (
    Campania,
    CampaniaHistorica,
    CompatibilidadCultivoSuelo,
    Costo,
    Cultivo,
    HistorialLoteCultivo,
    ImpactoRotacion,
    Lote,
    NivelAntiguedad,
    RendimientoCultivoSuelo,
    SecuenciaPermitida,
    SetupCultivo,
    SlotSiembra,
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


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "superficie_ha",
        "max_cultivos_principales",
        "max_cultivos_secundarios",
        "tipo_suelo",
    )
    list_filter = ("tipo_suelo",)
    search_fields = ("codigo", "nombre")


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
    list_display = ("codigo", "orden")
    search_fields = ("codigo",)


@admin.register(HistorialLoteCultivo)
class HistorialLoteCultivoAdmin(admin.ModelAdmin):
    list_display = ("lote", "cultivo", "campania_historica", "presente")
    list_filter = ("campania_historica", "presente")
    search_fields = ("lote__codigo", "cultivo__codigo")
