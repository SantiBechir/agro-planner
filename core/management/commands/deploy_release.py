from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Aplica migraciones; la carga global y personal se ejecuta explícitamente."

    def handle(self, *args, **options):
        self.stdout.write("Verificando coherencia de modelos y migraciones...")
        call_command("makemigrations", check=True, dry_run=True, interactive=False)
        self.stdout.write("Aplicando migraciones...")
        call_command("migrate", interactive=False)
