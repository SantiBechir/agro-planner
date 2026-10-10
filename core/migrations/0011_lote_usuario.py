from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.db.models.functions.text


def eliminar_lotes_existentes(apps, schema_editor):
    # Los lotes históricos eran compartidos. Se eliminan para iniciar la
    # separación por usuario sin exponer datos previos a nadie.
    apps.get_model("core", "Lote").objects.all().delete()


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ("core", "0010_cultivo_creado_por"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(eliminar_lotes_existentes, migrations.RunPython.noop),
        migrations.AddField(
            model_name="lote",
            name="usuario",
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="lotes",
                null=True,
                blank=True,
            ),
        ),
        migrations.AlterField(
            model_name="lote",
            name="codigo",
            field=models.CharField(max_length=50),
        ),
        migrations.RemoveConstraint(
            model_name="lote",
            name="unique_lote_nombre_ci",
        ),
        migrations.AddConstraint(
            model_name="lote",
            constraint=models.UniqueConstraint(
                fields=("usuario", "codigo"),
                name="unique_lote_codigo_usuario",
            ),
        ),
        migrations.AddConstraint(
            model_name="lote",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("nombre"),
                "usuario",
                name="unique_lote_nombre_ci_usuario",
            ),
        ),
    ]
