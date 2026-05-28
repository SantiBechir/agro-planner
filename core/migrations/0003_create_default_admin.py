from django.db import migrations

def create_admin(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    if not User.objects.filter(username='santi').exists():
        User.objects.create_superuser(
            username='santi',
            email='santiagobechir05@gmail.com',
            password='Abc12345'
        )

def remove_admin(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    User.objects.filter(username='santi').delete()

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0002_planificacion_asignacionloteslot'),
    ]

    operations = [
        migrations.RunPython(create_admin, reverse_code=remove_admin),
    ]
