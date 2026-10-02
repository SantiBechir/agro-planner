from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_existing_plans_to_account(apps, schema_editor):
    Planificacion = apps.get_model("core", "Planificacion")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    fallback_user = User.objects.filter(is_superuser=True).order_by("date_joined", "pk").first()
    if fallback_user is None:
        fallback_user = User.objects.order_by("date_joined", "pk").first()
    if fallback_user is not None:
        Planificacion.objects.filter(usuario__isnull=True).update(usuario_id=fallback_user.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_planificacion_escenarios"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="planificacion",
            name="usuario",
            field=models.ForeignKey(
                to=settings.AUTH_USER_MODEL,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="planificaciones",
                null=True,
                blank=True,
            ),
        ),
        migrations.RunPython(assign_existing_plans_to_account, migrations.RunPython.noop),
    ]
