from django.db import models


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

    def __str__(self):
        return self.nombre


class Lote(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=100, blank=True)
    superficie_ha = models.FloatField()
    max_cultivos_principales = models.PositiveIntegerField()
    max_cultivos_secundarios = models.PositiveIntegerField()
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.PROTECT)

    def __str__(self):
        return self.nombre or self.codigo


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
    orden = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo


class HistorialLoteCultivo(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE)
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    campania_historica = models.ForeignKey(
        CampaniaHistorica, on_delete=models.CASCADE
    )
    presente = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lote", "cultivo", "campania_historica"],
                name="unique_historial_lote_cultivo_campania",
            )
        ]

    def __str__(self):
        return f"{self.lote.codigo} - {self.cultivo.codigo} - {self.campania_historica.codigo}"
