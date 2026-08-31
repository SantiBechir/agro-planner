from django.db import models
from django.db.models.functions import Lower


# Fallback start year of the current planning campaign, used when the first
# planning campaign (C1) has no fecha_inicio to anchor year labels on.
ANIO_INICIO_CAMPANIA_ACTUAL = 2025


class TipoSuelo(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.nombre or self.codigo


class Campania(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    orden = models.PositiveIntegerField(unique=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo


class SlotSiembra(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    orden = models.PositiveIntegerField(unique=True)
    campania = models.ForeignKey(
        Campania, on_delete=models.PROTECT, related_name="slots"
    )

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo


class NivelAntiguedad(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    orden = models.PositiveIntegerField(unique=True)
    lag = models.IntegerField()
    alfa = models.FloatField(default=0)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo


class Cultivo(models.Model):
    class Tipo(models.TextChoices):
        PRINCIPAL = "principal", "Principal"
        SECUNDARIO = "secundario", "Secundario"
        OTRO = "otro", "Otro"

    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(
        max_length=20, choices=Tipo.choices, default=Tipo.OTRO
    )
    duracion_dias = models.IntegerField()
    siembra_inicio = models.IntegerField()
    siembra_fin = models.IntegerField()
    no_repetir_sin_intermedio = models.BooleanField(default=False)
    habilitado_optimizacion = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class Lote(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=100)
    superficie_ha = models.FloatField()
    max_cultivos_principales = models.PositiveIntegerField()
    max_cultivos_secundarios = models.PositiveIntegerField()
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.PROTECT)
    habilitado = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"), name="unique_lote_nombre_ci"
            )
        ]

    def __str__(self):
        return self.nombre or self.codigo


class Ambiente(models.Model):
    class Rendimiento(models.TextChoices):
        ALTO = "A", "Alto"
        MEDIO = "M", "Medio"
        BAJO = "B", "Bajo"

    lote = models.ForeignKey(
        Lote, on_delete=models.CASCADE, related_name="ambientes"
    )
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.PROTECT)
    rendimiento_esperado = models.CharField(
        max_length=1, choices=Rendimiento.choices
    )
    superficie_ha = models.FloatField()

    class Meta:
        unique_together = ("lote", "tipo_suelo")

    def __str__(self):
        return (
            f"{self.lote.codigo} / {self.tipo_suelo.codigo} "
            f"[{self.get_rendimiento_esperado_display()}] {self.superficie_ha} ha"
        )


class TipoCosto(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=200)
    unidad = models.CharField(max_length=50, blank=True)
    es_porcentual = models.BooleanField(default=False)

    def __str__(self):
        return self.codigo


class Costo(models.Model):
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    tipo_costo = models.ForeignKey(TipoCosto, on_delete=models.PROTECT)
    valor = models.FloatField()
    configurado = models.BooleanField(default=True)
    campania = models.ForeignKey(
        Campania, on_delete=models.CASCADE, null=True, blank=True
    )
    lote = models.ForeignKey(
        Lote, on_delete=models.CASCADE, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo", "tipo_costo", "campania", "lote"],
                name="unique_costo_cultivo_tipo_campania_lote",
            )
        ]

    def __str__(self):
        return f"{self.tipo_costo.codigo} - {self.cultivo.codigo}"


class RendimientoCultivoSuelo(models.Model):
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.CASCADE)
    valor = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo", "tipo_suelo"],
                name="unique_rendimiento_cultivo_suelo",
            )
        ]

    def __str__(self):
        return f"{self.cultivo.codigo} / {self.tipo_suelo.codigo}"


class CompatibilidadCultivoSuelo(models.Model):
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.CASCADE)
    compatible = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo", "tipo_suelo"],
                name="unique_compatibilidad_cultivo_suelo",
            )
        ]

    def __str__(self):
        estado = "compatible" if self.compatible else "no compatible"
        return f"{self.cultivo.codigo} / {self.tipo_suelo.codigo} [{estado}]"


class SetupCultivo(models.Model):
    cultivo_previo = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="setups_como_previo",
    )
    cultivo_siguiente = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="setups_como_siguiente",
    )
    dias = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo_previo", "cultivo_siguiente"],
                name="unique_setup_cultivo_previo_siguiente",
            )
        ]

    def __str__(self):
        return f"{self.cultivo_previo.codigo} → {self.cultivo_siguiente.codigo} ({self.dias}d)"


class SecuenciaPermitida(models.Model):
    cultivo_previo = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="secuencias_como_previo",
    )
    cultivo_siguiente = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="secuencias_como_siguiente",
    )
    permitido = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo_previo", "cultivo_siguiente"],
                name="unique_secuencia_cultivo_previo_siguiente",
            )
        ]

    def __str__(self):
        estado = "permitido" if self.permitido else "no permitido"
        return f"{self.cultivo_previo.codigo} → {self.cultivo_siguiente.codigo} [{estado}]"


class ImpactoRotacion(models.Model):
    cultivo_previo = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="impactos_como_previo",
    )
    cultivo_actual = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="impactos_como_actual",
    )
    valor = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo_previo", "cultivo_actual"],
                name="unique_impacto_rotacion_previo_actual",
            )
        ]

    def __str__(self):
        return f"{self.cultivo_previo.codigo} → {self.cultivo_actual.codigo}: {self.valor}"


class CampaniaHistorica(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    anio_inicio = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ["-anio_inicio"]

    @classmethod
    def anio_base_actual(cls):
        """Start year of the current planning campaign.

        Anchored on the fecha_inicio year of the first planning campaign
        (C1); falls back to ANIO_INICIO_CAMPANIA_ACTUAL when C1 has no
        fecha_inicio. Single source of truth for "current campaign year".
        """
        campania_base = Campania.objects.order_by("orden").first()
        if campania_base is not None and campania_base.fecha_inicio:
            return campania_base.fecha_inicio.year
        return ANIO_INICIO_CAMPANIA_ACTUAL

    @property
    def etiqueta(self):
        """Producer-facing year label, e.g. "2024/2025"."""
        return f"{self.anio_inicio}/{self.anio_inicio + 1}"

    def __str__(self):
        return self.etiqueta


class HistorialLoteCultivo(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE)
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    campania_historica = models.ForeignKey(
        CampaniaHistorica, on_delete=models.CASCADE
    )
    presente = models.BooleanField(default=True)
    rendimiento_kg_ha = models.FloatField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lote", "cultivo", "campania_historica"],
                name="unique_historial_lote_cultivo_campania",
            )
        ]

    def __str__(self):
        return f"{self.lote.codigo} - {self.cultivo.codigo} - {self.campania_historica.codigo}"


class Planificacion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EJECUTANDO = "ejecutando", "Ejecutando"
        COMPLETADO = "completado", "Completado"
        ERROR = "error", "Error"

    nombre = models.CharField(max_length=100)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    profit = models.FloatField(null=True, blank=True)
    ilu = models.FloatField(null=True, blank=True)
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.PENDIENTE
    )

    class Meta:
        ordering = ["-fecha_creacion"]

    def __str__(self):
        return f"{self.nombre} ({self.fecha_creacion.strftime('%d/%m/%Y %H:%M')})"


class AsignacionLoteSlot(models.Model):
    planificacion = models.ForeignKey(
        Planificacion, on_delete=models.CASCADE, related_name="asignaciones"
    )
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE)
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    slot = models.ForeignKey(SlotSiembra, on_delete=models.CASCADE)
    dia_siembra = models.FloatField(null=True, blank=True)
    dia_cosecha = models.FloatField(null=True, blank=True)
    rendimiento = models.FloatField(null=True, blank=True)
    ingreso = models.FloatField(null=True, blank=True)
    costo = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.planificacion.nombre} - {self.lote.codigo} - {self.cultivo.codigo} ({self.slot.codigo})"
