from django.core.management.base import BaseCommand, CommandError

from core.services.input_v51 import (
    InputValidationError, initialize_model_v51, read_and_validate_input_v51,
)


class Command(BaseCommand):
    help = "Inicializa las referencias globales sin reemplazar reglas existentes."

    def add_arguments(self, parser):
        parser.add_argument("archivo")

    def handle(self, *args, **options):
        try:
            stats = initialize_model_v51(read_and_validate_input_v51(options["archivo"]))
        except (InputValidationError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        for warning in stats.warnings:
            self.stdout.write(self.style.WARNING(warning))
        for line in stats.lines():
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS("Modelo global verificado."))
