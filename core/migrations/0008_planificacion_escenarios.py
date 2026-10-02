import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_limitesuperficiecultivocampania"),
    ]

    operations = [
        migrations.AddField(
            model_name="planificacion",
            name="origen",
            field=models.ForeignKey(
                to="core.planificacion",
                on_delete=django.db.models.deletion.SET_NULL,
                null=True,
                blank=True,
                related_name="replanificaciones",
            ),
        ),
        migrations.AddField(
            model_name="planificacion",
            name="escenario",
            field=models.JSONField(default=dict, blank=True),
        ),
        migrations.AddField(
            model_name="planificacion",
            name="datos_entrada",
            field=models.JSONField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="planificacion",
            name="detalle_error",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="planificacion",
            name="estado",
            field=models.CharField(
                max_length=20,
                default="pendiente",
                choices=[
                    ("pendiente", "Pendiente"),
                    ("ejecutando", "Ejecutando"),
                    ("completado", "Completado"),
                    ("infactible", "Infactible"),
                    ("error", "Error"),
                ],
            ),
        ),
    ]
