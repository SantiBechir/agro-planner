from unittest.mock import patch

from django.urls import reverse

from core.models import AsignacionLoteSlot, Planificacion, SlotSiembra
from .service_support import ServiceTestCase


class PlanificacionStatusTest(ServiceTestCase):
    def test_both_endpoints_preserve_all_states_and_completed_results(self):
        self.client.force_login(self.reader)
        plan = Planificacion.objects.create(nombre="Estados")
        slot = SlotSiembra.objects.create(codigo="T1", orden=1, campania=self.campania)
        AsignacionLoteSlot.objects.create(
            planificacion=plan, lote=self.lote, cultivo=self.cultivo, slot=slot,
            dia_siembra=1, dia_cosecha=120, ingreso=1000, costo=250,
        )
        with patch("core.services.solver.run_optimization") as solver:
            for state in Planificacion.Estado.values:
                plan.estado = state
                plan.save(update_fields=["estado"])
                for name in ("planificacion_status", "planificacion_status_partial"):
                    with self.subTest(state=state, endpoint=name):
                        response = self.client.get(reverse(name, args=[plan.pk]))
                        self.assertEqual(response.status_code, 200)
                        expected = "core/planificacion_status.html" if state in (
                            Planificacion.Estado.PENDIENTE, Planificacion.Estado.EJECUTANDO,
                        ) else "core/resultados_planificacion.html"
                        self.assertTemplateUsed(response, expected)
                        self.assertEqual(response.context["planificacion"].estado, state)
                        if state == Planificacion.Estado.COMPLETADO:
                            self.assertEqual(response.context["gantt_data"][0]["profit"], 750)
                            self.assertEqual(response.context["lotes_list"], ["J1"])
                        elif state == Planificacion.Estado.ERROR:
                            self.assertIn("Ocurrió un error al ejecutar el solver", response.context["error"])
            solver.assert_not_called()
        plan.refresh_from_db()
        self.assertEqual(plan.estado, Planificacion.Estado.ERROR)

    def test_unknown_plan_remains_404_on_both_endpoints(self):
        self.client.force_login(self.reader)
        for name in ("planificacion_status", "planificacion_status_partial"):
            self.assertEqual(self.client.get(reverse(name, args=[999])).status_code, 404)
