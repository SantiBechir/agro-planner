from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_cultivo_habilitado_costo_configurado"),
    ]

    operations = [
        migrations.CreateModel(
            name="SueloLote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("proporcion", models.FloatField()),
                ("nivel_productividad", models.CharField(choices=[("A", "Alto"), ("M", "Medio"), ("B", "Bajo")], default="M", max_length=1)),
                ("lote", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="suelos", to="core.lote")),
                ("tipo_suelo", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="core.tiposuelo")),
            ],
        ),
        migrations.AddConstraint(
            model_name="suelolote",
            constraint=models.UniqueConstraint(fields=("lote", "tipo_suelo"), name="unique_suelo_lote"),
        ),
    ]
