from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.services.legacy import asignar_datos_legacy


class Command(BaseCommand):
    help = "Asigna los datos antiguos sin propietario a una cuenta existente."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True)

    def handle(self, *args, **options):
        try:
            usuario = get_user_model().objects.get(email__iexact=options["usuario"].strip(), is_active=True)
        except get_user_model().DoesNotExist as exc:
            raise CommandError("No existe una cuenta activa con ese correo.") from exc
        try:
            costos, limites = asignar_datos_legacy(usuario)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS(f"Asignados {costos} costos y {limites} límites."))
