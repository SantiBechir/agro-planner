from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, override_settings
from django.urls import reverse

from core.models import Ambiente, Costo, HistorialLoteCultivo, Lote, Planificacion
from core.services import costos, cultivos, historial, lotes, planificaciones
from .service_support import ServiceTestCase


class InputSecurityTest(ServiceTestCase):
    def test_nonfinite_numbers_are_rejected_without_modifying_global_data(self):
        for raw in ("nan", "inf", "-inf", "1e999"):
            with self.subTest(raw=raw):
                operations = (
                    lambda: costos.actualizar_costos(self.editor, {self.costo.pk: raw}),
                    lambda: lotes.crear_lote(self.editor, nombre="Invalid", ambientes=[(self.suelo.pk, "M", raw)]),
                    lambda: cultivos.crear_cultivo(self.editor, **{**self.datos_cultivo(), "rendimientos": {self.suelo.pk: raw}}),
                    lambda: historial.cargar_historial(self.editor, self.lote.pk, anio_inicio=2024, cultivo_1_id=self.cultivo.pk, rendimiento_1=raw),
                )
                for operation in operations:
                    with self.assertRaises(ValidationError):
                        operation()
        self.costo.refresh_from_db()
        self.assertEqual(self.costo.valor, 100)
        self.assertEqual(Lote.objects.count(), 1)
        self.assertEqual(Ambiente.objects.count(), 1)
        self.assertFalse(HistorialLoteCultivo.objects.exists())

    def test_oversized_and_empty_names_are_rejected(self):
        for name in ("", " " * 5, "a" * 101):
            with self.assertRaises(ValidationError):
                planificaciones.solicitar_planificacion(self.reader, nombre=name)
            with self.assertRaises(ValidationError):
                lotes.crear_lote(self.editor, nombre=name, ambientes=[(self.suelo.pk, "M", 10)])
        self.assertFalse(Planificacion.objects.exists())

    def test_invalid_crop_ids_raise_validation_error_instead_of_server_error(self):
        for raw in ("invalid", "1e300", ""):
            with self.assertRaises(ValidationError):
                historial.cargar_historial(self.editor, self.lote.pk, anio_inicio=2024, cultivo_1_id=raw)

    def test_disabled_users_cannot_call_write_services(self):
        self.editor.is_active = False
        self.reader.is_active = False
        with self.assertRaises(PermissionDenied):
            lotes.alternar_lote(self.editor, self.lote.pk)
        with self.assertRaises(PermissionDenied):
            planificaciones.solicitar_planificacion(self.reader, nombre="No")

    @override_settings(MAX_ACTIVE_PLANIFICATIONS=2)
    def test_queue_limit_counts_running_jobs_and_reopens_after_completion(self):
        first = planificaciones.solicitar_planificacion(self.reader, nombre="1")
        second = planificaciones.solicitar_planificacion(self.reader, nombre="2")
        second.estado = Planificacion.Estado.EJECUTANDO
        second.save()
        with self.assertRaises(ValidationError):
            planificaciones.solicitar_planificacion(self.reader, nombre="3")
        self.assertEqual(Planificacion.objects.count(), 2)
        first.estado = Planificacion.Estado.COMPLETADO
        first.save()
        planificaciones.solicitar_planificacion(self.reader, nombre="3")

    def test_authenticated_writes_require_csrf_tokens(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.editor)
        urls = (
            reverse("lote_create"), reverse("lote_toggle", args=[self.lote.pk]),
            reverse("lote_update", args=[self.lote.pk]), reverse("cultivo_create"),
            reverse("costo_list"), reverse("ejecutar_optimizacion"),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(client.post(url, {}).status_code, 403)

    def test_unknown_host_is_rejected(self):
        self.assertEqual(self.client.get(reverse("login"), HTTP_HOST="attacker.invalid").status_code, 400)
