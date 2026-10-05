from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from core.views import ejecutar_optimizacion
from accounts.roles import READER_ROLE, set_functional_role
from core.models import (
    Campania,
    CompatibilidadCultivoSuelo,
    Cultivo,
    LimiteSuperficieCultivoCampania,
    Lote,
    Planificacion,
    TipoSuelo,
)
from core.services.planificaciones import solicitar_planificacion
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
        suelo = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        Lote.objects.create(
            codigo="J1", nombre="Activo", superficie_ha=100,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=True,
        )
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

    def test_rejects_when_enabled_lots_cannot_cover_required_minimum(self):
        suelo = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        Lote.objects.create(
            codigo="J1", nombre="Activo", superficie_ha=50,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=True,
        )
        Lote.objects.create(
            codigo="J2", nombre="Desactivado", superficie_ha=100,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=False,
        )
        cultivo = Cultivo.objects.create(
            codigo="RGRASS", nombre="R. Grass", tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120, siembra_inicio=10, siembra_fin=90,
        )
        campania = Campania.objects.create(
            codigo="C1", orden=1, fecha_inicio="2025-06-01", fecha_fin="2026-05-31",
        )
        CompatibilidadCultivoSuelo.objects.create(
            cultivo=cultivo, tipo_suelo=suelo, compatible=True,
        )
        LimiteSuperficieCultivoCampania.objects.create(
            cultivo=cultivo, campania=campania, min_ha=60, max_ha=60,
        )

        with self.assertRaisesMessage(ValidationError, "se requieren al menos 60 ha"):
            solicitar_planificacion(self.user, nombre="Planificación de prueba")

        self.assertFalse(Planificacion.objects.exists())

    def test_rejects_when_no_enabled_lot_combination_reaches_exact_limit(self):
        suelo = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        for codigo, superficie in (("J1", 50), ("J2", 40)):
            Lote.objects.create(
                codigo=codigo, nombre=f"Lote {codigo}", superficie_ha=superficie,
                max_cultivos_principales=10, max_cultivos_secundarios=10,
                tipo_suelo=suelo, habilitado=True,
            )
        cultivo = Cultivo.objects.create(
            codigo="RGRASS", nombre="R. Grass", tipo=Cultivo.Tipo.OTRO,
            duracion_dias=120, siembra_inicio=10, siembra_fin=90,
            no_repetir_sin_intermedio=True,
        )
        campania = Campania.objects.create(
            codigo="C1", orden=1, fecha_inicio="2025-06-01", fecha_fin="2026-05-31",
        )
        CompatibilidadCultivoSuelo.objects.create(
            cultivo=cultivo, tipo_suelo=suelo, compatible=True,
        )
        LimiteSuperficieCultivoCampania.objects.create(
            cultivo=cultivo, campania=campania, min_ha=60, max_ha=60,
        )

        with self.assertRaisesMessage(ValidationError, "requiere exactamente 60 ha"):
            solicitar_planificacion(self.user, nombre="Planificación de prueba")


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
