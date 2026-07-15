from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_create_default_admin"),
    ]

    operations = [
        migrations.AddField(
            model_name="cultivo",
            name="habilitado_optimizacion",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="costo",
            name="configurado",
            field=models.BooleanField(default=True),
        ),
    ]
