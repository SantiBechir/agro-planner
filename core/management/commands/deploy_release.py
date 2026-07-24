import os
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Aplica migraciones y carga Input v1 en la base desplegada."

    def handle(self, *args, **options):
        self.stdout.write("Aplicando migraciones...")
        call_command("migrate", interactive=False)

        input_path = Path(
            os.getenv("INPUT_DATA_FILE", "docs/Input v1.xlsx")
        )
        if not input_path.is_absolute():
            input_path = Path(settings.BASE_DIR) / input_path

        if not input_path.is_file():
            raise CommandError(
                f"No se encontro el archivo de datos: {input_path}"
            )

        self.stdout.write(f"Cargando datos desde {input_path}...")
        call_command("cargar_input", str(input_path))
