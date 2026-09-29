from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from core.views import ejecutar_optimizacion
from accounts.roles import READER_ROLE, set_functional_role
from core.models import Planificacion
from django.template.loader import render_to_string


User = get_user_model()


class EjecutarOptimizacionDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            password="password",
        )
        set_functional_role(self.user, READER_ROLE)
        self.factory = RequestFactory()

    def test_creates_pending_job_without_running_solver_in_request(self):
        request = self.factory.post(
            "/planificaciones/ejecutar/",
            {"nombre": "Planificacion asincrona"},
        )
        request.user = self.user

        response = ejecutar_optimizacion(request)

        planificacion = Planificacion.objects.get(nombre="Planificacion asincrona")
        self.assertEqual(planificacion.estado, Planificacion.Estado.PENDIENTE)
        self.assertRedirects(
            response,
            f"/planificaciones/{planificacion.id}/estado/",
            fetch_redirect_response=False,
        )


class ResultadosPlanificacionTemplateTest(TestCase):
    def test_renders_assignment_cost_instead_of_template_expression(self):
        html = render_to_string(
            "core/resultados_planificacion.html",
            {
                "planificacion": Planificacion(nombre="Prueba", profit=20538.48, ilu=1),
                "gantt_data": [{
                    "lote": "J7",
                    "slot": "T5",
                    "cultivo": "CARINATA",
                    "fecha_siembra": "31/03/2028",
                    "fecha_cosecha": "30/10/2028",
                    "profit": 20538.48,
                    "ingreso": 42358,
                    "costo": 21819.52,
                }],
                "lotes_list": ["J7"],
            },
        )

        self.assertNotIn("bar.costo|floatformat", html)
        self.assertIn("Cost: $21820 [USD/ha]", html)
