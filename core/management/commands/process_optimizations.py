import time
import traceback

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Planificacion
from core.services.solver import run_optimization


class Command(BaseCommand):
    help = "Procesa planificaciones pendientes en segundo plano."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Ejecutar en bucle hasta que se interrumpa.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=5,
            help="Segundos de espera entre iteraciones en modo loop (default: 5).",
        )

    def handle(self, *args, **options):
        loop = options["loop"]
        interval = options["interval"]

        if loop:
            self.stdout.write(self.style.SUCCESS("Worker iniciado en modo loop..."))
            while True:
                self._process_one()
                time.sleep(interval)
        else:
            processed = self._process_one()
            if not processed:
                self.stdout.write("No hay planificaciones pendientes.")

    def _process_one(self):
        planificacion_id = None
        try:
            with transaction.atomic():
                planificacion = (
                    Planificacion.objects.select_for_update(skip_locked=True)
                    .filter(estado=Planificacion.Estado.PENDIENTE)
                    .order_by("fecha_creacion")
                    .first()
                )
                if not planificacion:
                    return False

                planificacion.estado = Planificacion.Estado.EJECUTANDO
                planificacion.save()
                planificacion_id = planificacion.id

            self.stdout.write(f"Procesando planificacion {planificacion_id}...")
            run_optimization(planificacion_id)
            self.stdout.write(
                self.style.SUCCESS(f"Planificacion {planificacion_id} finalizada.")
            )
            return True
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"Error procesando planificacion {planificacion_id}: {e}")
            )
            traceback.print_exc()
            if planificacion_id:
                try:
                    plan = Planificacion.objects.get(pk=planificacion_id)
                    plan.estado = Planificacion.Estado.ERROR
                    plan.save()
                except Exception:
                    pass
            return False
