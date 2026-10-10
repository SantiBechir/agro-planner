from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_lote_usuario"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="limitesuperficiecultivocampania",
            name="usuario",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="limites_superficie",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="limitesuperficiecultivocampania",
            name="unique_limite_cultivo_campania",
        ),
        migrations.AddConstraint(
            model_name="limitesuperficiecultivocampania",
            constraint=models.UniqueConstraint(
                fields=("usuario", "cultivo", "campania"),
                name="unique_limite_cultivo_campania_usuario",
            ),
        ),
    ]