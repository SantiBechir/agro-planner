from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import CampaniaHistorica
from core.services.input_v51 import (
    InputValidationError,
    persist_input_v51,
    read_and_validate_input_v51,
)


def campania_historica_desde_columna_excel(ch_code):
    """Mapea CH1/CH2/CH3 al año anterior a la campaña de planificación."""
    lag = int(str(ch_code).strip().upper().removeprefix("CH"))
    base_year = CampaniaHistorica.anio_base_actual()
    existing = CampaniaHistorica.objects.filter(anio_inicio=base_year - lag).first()
    if existing:
        return existing, False
    return CampaniaHistorica.objects.get_or_create(
        anio_inicio=base_year - lag,
        defaults={"codigo": str(ch_code).strip().upper()},
    )


class Command(BaseCommand):
    help = "Valida e importa Input v5.1 como snapshot autoritativo."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=str, help="Ruta a Input v5.1.xlsx")
        parser.add_argument(
            "--validar",
            action="store_true",
            help="Valida el archivo completo sin escribir en la base.",
        )

    def handle(self, *args, **options):
        archivo = options["archivo"]
        validar = options.get("validar", False)
        self.stdout.write(f"Leyendo y validando {archivo}...")
        try:
            data = read_and_validate_input_v51(archivo)
        except InputValidationError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Validación completa: "
                f"{len(data.lotes)} lotes, {len(data.cultivos)} cultivos, "
                f"{len(data.suelos)} suelos, {len(data.campanias)} campañas, "
                f"{len(data.limites)} límites y {len(data.costos)} costos."
            )
        )
        if validar:
            self.stdout.write(self.style.SUCCESS("No se realizaron cambios en la base."))
            return

        try:
            with transaction.atomic():
                stats = persist_input_v51(data)
        except Exception as exc:
            raise CommandError(
                f"La importación fue revertida por completo: {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS("Importación completada."))
        for line in stats.lines():
            self.stdout.write(line)
