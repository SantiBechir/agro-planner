from django.contrib import admin

from .models import (
    Ambiente,
    AsignacionLoteSlot,
    Campania,
    CampaniaHistorica,
    CompatibilidadCultivoSuelo,
    Costo,
    ConfiguracionCultivoUsuario,
    Cultivo,
    HistorialLoteCultivo,
    ImpactoRotacion,
    LimiteSuperficieCultivoCampania,
    Lote,
    NivelAntiguedad,
    Planificacion,
    RendimientoCultivoSuelo,
    SecuenciaPermitida,
    SetupCultivo,
    SlotSiembra,
    TipoCosto,
    TipoSuelo,
)




class GlobalModelAdmin(admin.ModelAdmin):
    """Las reglas compartidas solo se administran con privilegios globales."""
    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)


class PrivateModelAdmin(admin.ModelAdmin):
    owner_lookup = "usuario"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(**{self.owner_lookup: request.user})

    def get_list_filter(self, request):
        return [
            (item, admin.RelatedOnlyFieldListFilter)
            if isinstance(item, str) and item in ("usuario", "lote", "planificacion") else item
            for item in super().get_list_filter(request)
        ]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "usuario":
            kwargs["required"] = True
            if not request.user.is_superuser:
                from django.contrib.auth import get_user_model
                kwargs["queryset"] = get_user_model().objects.filter(pk=request.user.pk)
                kwargs["initial"] = request.user.pk
        if not request.user.is_superuser and db_field.name in ("lote", "planificacion", "origen"):
            kwargs["queryset"] = db_field.remote_field.model.objects.filter(usuario=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class PrivateInline(admin.TabularInline):
    owner_lookup = "lote__usuario"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(**{self.owner_lookup: request.user})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser and db_field.name in ("lote", "planificacion", "origen"):
            kwargs["queryset"] = db_field.remote_field.model.objects.filter(usuario=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ConfiguracionCultivoUsuario)
class ConfiguracionCultivoUsuarioAdmin(PrivateModelAdmin):
    list_display = ("usuario", "cultivo", "habilitado_optimizacion")
    list_filter = ("usuario", "habilitado_optimizacion")


@admin.register(TipoSuelo)
class TipoSueloAdmin(GlobalModelAdmin):
    list_display = ("codigo", "nombre")
    search_fields = ("codigo", "nombre")


@admin.register(Campania)
class CampaniaAdmin(GlobalModelAdmin):
    list_display = ("codigo", "orden", "fecha_inicio", "fecha_fin")
    list_filter = ("orden",)
    search_fields = ("codigo",)


@admin.register(SlotSiembra)
class SlotSiembraAdmin(GlobalModelAdmin):
    list_display = ("codigo", "orden", "campania")
    list_filter = ("campania",)
    search_fields = ("codigo",)


@admin.register(NivelAntiguedad)
class NivelAntiguedadAdmin(GlobalModelAdmin):
    list_display = ("codigo", "orden", "lag", "alfa")
    ordering = ("orden",)


@admin.register(Cultivo)
class CultivoAdmin(GlobalModelAdmin):
    exclude = ("habilitado_optimizacion",)
    list_display = (
        "codigo",
        "nombre",
        "creado_por",
        "tipo",
        "duracion_dias",
        "siembra_inicio",
        "siembra_fin",
        "no_repetir_sin_intermedio",
    )
    list_filter = ("tipo", "no_repetir_sin_intermedio", "creado_por")
    search_fields = ("codigo", "nombre")


class AmbienteInline(PrivateInline):
    model = Ambiente
    extra = 0


@admin.register(Lote)
class LoteAdmin(PrivateModelAdmin):
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


@admin.register(TipoCosto)
class TipoCostoAdmin(GlobalModelAdmin):
    list_display = ("codigo", "descripcion", "unidad", "es_porcentual")
    search_fields = ("codigo", "descripcion")


@admin.register(Costo)
class CostoAdmin(PrivateModelAdmin):
    list_display = ("usuario", "cultivo", "tipo_costo", "valor", "campania", "lote")
    list_filter = ("tipo_costo", "campania", "lote")
    search_fields = ("cultivo__codigo", "tipo_costo__codigo")


@admin.register(LimiteSuperficieCultivoCampania)
class LimiteSuperficieCultivoCampaniaAdmin(PrivateModelAdmin):
    list_display = ("usuario", "cultivo", "campania", "min_ha", "max_ha")
    list_filter = ("campania", "cultivo")
    search_fields = ("cultivo__codigo", "campania__codigo")


@admin.register(RendimientoCultivoSuelo)
class RendimientoCultivoSueloAdmin(GlobalModelAdmin):
    list_display = ("cultivo", "tipo_suelo", "valor")
    list_filter = ("tipo_suelo",)
    search_fields = ("cultivo__codigo", "tipo_suelo__codigo")


@admin.register(CompatibilidadCultivoSuelo)
class CompatibilidadCultivoSueloAdmin(GlobalModelAdmin):
    list_display = ("cultivo", "tipo_suelo", "compatible")
    list_filter = ("tipo_suelo", "compatible")
    search_fields = ("cultivo__codigo", "tipo_suelo__codigo")


@admin.register(SetupCultivo)
class SetupCultivoAdmin(GlobalModelAdmin):
    list_display = ("cultivo_previo", "cultivo_siguiente", "dias")
    search_fields = (
        "cultivo_previo__codigo",
        "cultivo_siguiente__codigo",
    )


@admin.register(SecuenciaPermitida)
class SecuenciaPermitidaAdmin(GlobalModelAdmin):
    list_display = ("cultivo_previo", "cultivo_siguiente", "permitido")
    list_filter = ("permitido",)
    search_fields = (
        "cultivo_previo__codigo",
        "cultivo_siguiente__codigo",
    )


@admin.register(ImpactoRotacion)
class ImpactoRotacionAdmin(GlobalModelAdmin):
    list_display = ("cultivo_previo", "cultivo_actual", "valor")
    search_fields = (
        "cultivo_previo__codigo",
        "cultivo_actual__codigo",
    )


@admin.register(CampaniaHistorica)
class CampaniaHistoricaAdmin(GlobalModelAdmin):
    list_display = ("codigo", "anio_inicio")
    ordering = ("-anio_inicio",)
    search_fields = ("codigo",)


@admin.register(HistorialLoteCultivo)
class HistorialLoteCultivoAdmin(PrivateModelAdmin):
    owner_lookup = "lote__usuario"
    list_display = ("lote", "cultivo", "campania_historica", "presente")
    list_filter = ("campania_historica", "presente")
    search_fields = ("lote__codigo", "cultivo__codigo")


class AsignacionInline(PrivateInline):
    owner_lookup = "planificacion__usuario"
    model = AsignacionLoteSlot
    extra = 0
    raw_id_fields = ("lote", "cultivo", "slot")


@admin.register(Planificacion)
class PlanificacionAdmin(PrivateModelAdmin):
    list_display = ("nombre", "usuario", "fecha_creacion", "profit", "ilu", "estado")
    list_filter = ("estado", "fecha_creacion", "usuario")
    search_fields = ("nombre", "usuario__email")
    inlines = [AsignacionInline]


@admin.register(AsignacionLoteSlot)
class AsignacionLoteSlotAdmin(PrivateModelAdmin):
    owner_lookup = "planificacion__usuario"
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
