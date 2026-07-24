# CampaniaHistorica becomes year-based: anio_inicio replaces orden.

from django.db import migrations, models


# Base used to backfill anio_inicio from the legacy orden field.
# Matches ANIO_INICIO_CAMPANIA_ACTUAL: CH1 (orden 1) -> 2024, CH2 -> 2023,
# CH3 -> 2022.
ANIO_BASE_BACKFILL = 2025


def backfill_anio_inicio(apps, schema_editor):
    CampaniaHistorica = apps.get_model("core", "CampaniaHistorica")
    for campania in CampaniaHistorica.objects.all():
        campania.anio_inicio = ANIO_BASE_BACKFILL - campania.orden
        campania.save(update_fields=["anio_inicio"])


def restore_orden(apps, schema_editor):
    """Reverse-only step: repopulate orden from anio_inicio after the column
    is re-added, so the NOT NULL re-tighten below has values to work with."""
    CampaniaHistorica = apps.get_model("core", "CampaniaHistorica")
    for campania in CampaniaHistorica.objects.all():
        campania.orden = ANIO_BASE_BACKFILL - campania.anio_inicio
        campania.save(update_fields=["orden"])


def noop_reverse(apps, schema_editor):
    pass


def noop_forward(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_ambiente_historiallotecultivo_rendimiento_kg_ha_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaniahistorica",
            name="anio_inicio",
            field=models.PositiveIntegerField(null=True),
        ),
        migrations.RunPython(backfill_anio_inicio, noop_reverse),
        migrations.AlterField(
            model_name="campaniahistorica",
            name="anio_inicio",
            field=models.PositiveIntegerField(unique=True),
        ),
        # Make orden nullable before dropping it so reversing the RemoveField
        # below can re-add the column on a populated table (schema-reverse
        # sanity; the data part reverse stays a no-op).
        migrations.AlterField(
            model_name="campaniahistorica",
            name="orden",
            field=models.PositiveIntegerField(unique=True, null=True),
        ),
        migrations.RunPython(noop_forward, restore_orden),
        migrations.RemoveField(
            model_name="campaniahistorica",
            name="orden",
        ),
        migrations.AlterModelOptions(
            name="campaniahistorica",
            options={"ordering": ["-anio_inicio"]},
        ),
    ]
