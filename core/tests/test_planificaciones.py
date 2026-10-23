from core.models import ConfiguracionCultivoUsuario
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
        Lote.objects.create(usuario=self.user,
            codigo="J1", nombre="Activo", superficie_ha=100,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=True,
        )
        crop = Cultivo.objects.create(codigo="TRIGO", nombre="Trigo", duracion_dias=120, siembra_inicio=1, siembra_fin=60)
        ConfiguracionCultivoUsuario.objects.create(usuario=self.user, cultivo=crop, habilitado_optimizacion=True)
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
        Lote.objects.create(usuario=self.user,
            codigo="J1", nombre="Activo", superficie_ha=50,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=True,
        )
        Lote.objects.create(usuario=self.user,
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
        ConfiguracionCultivoUsuario.objects.create(usuario=self.user, cultivo=cultivo, habilitado_optimizacion=True)
        LimiteSuperficieCultivoCampania.objects.create(usuario=self.user,
            cultivo=cultivo, campania=campania, min_ha=60, max_ha=60,
        )

        with self.assertRaisesMessage(ValidationError, "mínimo de 60 ha"):
            solicitar_planificacion(self.user, nombre="Planificación de prueba")

        self.assertFalse(Planificacion.objects.exists())

    def test_rejects_when_no_enabled_lot_combination_reaches_exact_limit(self):
        suelo = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        for codigo, superficie in (("J1", 50), ("J2", 40)):
            Lote.objects.create(usuario=self.user,
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
        ConfiguracionCultivoUsuario.objects.create(usuario=self.user, cultivo=cultivo, habilitado_optimizacion=True)
        LimiteSuperficieCultivoCampania.objects.create(usuario=self.user,
            cultivo=cultivo, campania=campania, min_ha=60, max_ha=60,
        )

        with self.assertRaisesMessage(ValidationError, "configuraste exactamente 60 ha"):
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


from .service_support import ServiceTestCase
from core.services.optimization_inputs import build_pyomo_input_data
from django.urls import reverse


class LimitesEnPlanificacionTest(ServiceTestCase):
    def setUp(self):
        self.limite = LimiteSuperficieCultivoCampania.objects.create(
            usuario=self.editor, cultivo=self.cultivo, campania=self.campania,
            min_ha=0, max_ha=100,
        )
        self.url = reverse("planificacion_limites_update", args=[self.cultivo.pk])
        self.client.force_login(self.editor)

    def test_limits_are_in_planning_and_removed_from_crop_cards(self):
        response = self.client.get(reverse("planificacion_list"))
        self.assertContains(response, "Límites de superficie por cultivo")
        self.assertContains(response, self.url)
        self.assertContains(response, f'name="min_{self.limite.pk}"')
        self.assertNotContains(self.client.get(reverse("cultivo_list")), "Límites a cultivar")
        self.assertNotContains(self.client.get(reverse("cultivo_list")), self.url)

    def test_saved_personal_limits_are_consumed_by_the_optimizer(self):
        response = self.client.post(self.url, {
            f"min_{self.limite.pk}": "12.50", f"max_{self.limite.pk}": "90.75",
        }, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Guardado automáticamente")
        data = build_pyomo_input_data(self.editor)
        key = (self.cultivo.codigo, self.campania.codigo)
        self.assertEqual(data["minha_dict"][key], 12.5)
        self.assertEqual(data["maxha_dict"][key], 90.75)

    def test_invalid_campaign_does_not_partially_save_other_campaigns(self):
        campaign = Campania.objects.create(codigo="C2", orden=2)
        other = LimiteSuperficieCultivoCampania.objects.create(
            usuario=self.editor, cultivo=self.cultivo, campania=campaign, min_ha=0, max_ha=100,
        )
        response = self.client.post(self.url, {
            f"min_{self.limite.pk}": "10", f"max_{self.limite.pk}": "90",
            f"min_{other.pk}": "100", f"max_{other.pk}": "50",
        }, HTTP_HX_REQUEST="true")
        self.assertContains(response, "El mínimo no puede ser mayor")
        self.limite.refresh_from_db()
        self.assertEqual(self.limite.min_ha, 0)

    def test_foreign_limits_are_not_rendered_or_changed(self):
        other = LimiteSuperficieCultivoCampania.objects.create(
            usuario=self.reader, cultivo=self.cultivo, campania=self.campania, min_ha=25, max_ha=75,
        )
        self.assertNotContains(self.client.get(reverse("planificacion_list")), f'name="min_{other.pk}"')
        self.client.post(self.url, {
            f"min_{self.limite.pk}": "5", f"max_{self.limite.pk}": "80",
            f"min_{other.pk}": "0", f"max_{other.pk}": "0",
        }, HTTP_HX_REQUEST="true")
        other.refresh_from_db()
        self.assertEqual((other.min_ha, other.max_ha), (25, 75))

    def test_reader_cannot_save_and_get_cannot_mutate(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(self.reader)
        response = self.client.get(reverse("planificacion_list"))
        self.assertContains(response, "Límites de superficie por cultivo")
        self.assertNotContains(response, f'hx-post="{self.url}"')
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, {}).status_code, 302)
