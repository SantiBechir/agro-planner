from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from core.models import Ambiente, Costo, Cultivo, HistorialLoteCultivo, Lote, Planificacion
from core.services import costos, cultivos, historial, lotes, planificaciones
from .service_support import ServiceTestCase


class ServiceAuthorizationTest(ServiceTestCase):
    def test_agricultural_writes_reject_reader_and_anonymous_without_changes(self):
        models = (Lote, Ambiente, Cultivo, Costo, HistorialLoteCultivo, Planificacion)
        before = [list(model.objects.order_by("pk").values()) for model in models]
        for actor in (self.reader, AnonymousUser()):
            operations = (
                lambda: lotes.crear_lote(actor, nombre="Nuevo", ambientes=[(self.suelo.pk, "M", 10)]),
                lambda: lotes.actualizar_lote(actor, self.lote.pk, nombre="Otro", ambientes=[], habilitado=False),
                lambda: lotes.alternar_lote(actor, self.lote.pk),
                lambda: historial.cargar_historial(actor, self.lote.pk, anio_inicio=2024, cultivo_1_id=self.cultivo.pk),
                lambda: historial.eliminar_historial(actor, self.lote.pk, anio_inicio=2024),
                lambda: cultivos.crear_cultivo(actor, **self.datos_cultivo()),
                lambda: costos.actualizar_costos(actor, {self.costo.pk: 200}, cultivo_id=self.cultivo.pk, habilitar=True),
            )
            for index, operation in enumerate(operations):
                with self.subTest(actor=str(actor), operation=index):
                    with self.assertRaises(PermissionDenied):
                        operation()
        self.assertEqual(before, [list(model.objects.order_by("pk").values()) for model in models])

    def test_authenticated_reader_can_request_plan_but_anonymous_cannot(self):
        with self.assertRaises(PermissionDenied):
            planificaciones.solicitar_planificacion(AnonymousUser(), nombre="No")
        self.assertFalse(Planificacion.objects.exists())
        plan = planificaciones.solicitar_planificacion(self.reader, nombre="Plan lector")
        self.assertEqual(plan.estado, Planificacion.Estado.PENDIENTE)
        self.assertFalse(plan.asignaciones.exists())

    def test_superuser_without_editor_group_can_write(self):
        self.reader.is_superuser = True
        lote = lotes.alternar_lote(self.reader, self.lote.pk)
        self.assertFalse(lote.habilitado)
