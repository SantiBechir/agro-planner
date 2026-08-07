from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from io import StringIO
from unittest.mock import patch
from core.views import cultivo_list, lote_list, lote_create, cultivo_create, costo_list, ejecutar_optimizacion
from core.models import Cultivo, TipoSuelo, RendimientoCultivoSuelo, Lote, CompatibilidadCultivoSuelo, TipoCosto, Costo, Campania, Planificacion
from core.management.commands.process_optimizations import Command as ProcessOptimizationsCommand
from core.services.optimization_inputs import build_pyomo_input_data
from django.template.loader import render_to_string
from datetime import datetime, timedelta

class CultivoListDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.factory = RequestFactory()
        
        # Create TipoSuelo
        self.suelo1 = TipoSuelo.objects.create(codigo="S1", nombre="Suelo 1")
        self.suelo2 = TipoSuelo.objects.create(codigo="S2", nombre="Suelo 2")
        
        # Create Cultivo
        self.cultivo = Cultivo.objects.create(
            codigo="SOJA_TEST",
            nombre="Soja Test",
            tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120,
            siembra_inicio=10,
            siembra_fin=90,
            no_repetir_sin_intermedio=False
        )
        
        # Create Rendimientos
        RendimientoCultivoSuelo.objects.create(cultivo=self.cultivo, tipo_suelo=self.suelo1, valor=4.5)
        RendimientoCultivoSuelo.objects.create(cultivo=self.cultivo, tipo_suelo=self.suelo2, valor=3.2)
        
    def test_cultivo_list_direct_call(self):
        request = self.factory.get('/cultivos/')
        request.user = self.user
        
        response = cultivo_list(request)
        self.assertEqual(response.status_code, 200)
        
        # Verify rendered HTML content directly
        html = response.content.decode('utf-8')
        
        # Base year and base date calculation
        base_year = datetime.now().year
        base_date = datetime(base_year, 6, 1)
        expected_inicio = (base_date + timedelta(days=9)).strftime("%d/%m/%Y")
        expected_fin = (base_date + timedelta(days=89)).strftime("%d/%m/%Y")
        
        self.assertIn("Suelo S1", html)
        self.assertTrue("4.5" in html or "4,5" in html, f"Expected 4.5 or 4,5 in html, got: {html}")
        self.assertIn("Suelo S2", html)
        self.assertTrue("3.2" in html or "3,2" in html, f"Expected 3.2 or 3,2 in html, got: {html}")
        self.assertIn(expected_inicio, html)
        self.assertIn(expected_fin, html)


class LoteCreateDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.factory = RequestFactory()
        self.suelo1 = TipoSuelo.objects.create(codigo="S1", nombre="Suelo 1")

    def test_lote_create_and_list(self):
        # Create a lote
        data = {
            "codigo": "LOTE_TEST",
            "nombre": "Nombre Lote Test",
            "superficie_ha": "250.5",
            "max_cultivos_principales": "3",
            "max_cultivos_secundarios": "2",
            "tipo_suelo": str(self.suelo1.id)
        }
        request = self.factory.post('/lotes/crear/', data)
        request.user = self.user
        
        # Mock messages framework
        from django.contrib.messages.storage.base import BaseStorage
        class DummyStorage(BaseStorage):
            def _get(self):
                return [], True
            def _store(self, messages, response, *args, **kwargs):
                return []
        setattr(request, '_messages', DummyStorage(request))

        response = lote_create(request)
        self.assertEqual(response.status_code, 200)

        # Verify DB entry
        lote_obj = Lote.objects.get(codigo="LOTE_TEST")
        self.assertEqual(lote_obj.nombre, "Nombre Lote Test")
        self.assertEqual(lote_obj.superficie_ha, 250.5)
        self.assertEqual(lote_obj.max_cultivos_principales, 3)
        self.assertEqual(lote_obj.max_cultivos_secundarios, 2)
        self.assertEqual(lote_obj.tipo_suelo, self.suelo1)

        # Verify rendered HTML
        html = response.content.decode('utf-8')
        self.assertIn("LOTE_TEST", html)
        self.assertIn("Suelo Suelo 1", html)


class CultivoCreateDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.factory = RequestFactory()
        self.suelo1 = TipoSuelo.objects.create(codigo="S1", nombre="Suelo 1")
        self.campania1 = Campania.objects.create(codigo="C1", orden=1)
        self.campania2 = Campania.objects.create(codigo="C2", orden=2)
        Lote.objects.create(
            codigo="L1",
            nombre="Lote 1",
            superficie_ha=100,
            max_cultivos_principales=2,
            max_cultivos_secundarios=1,
            tipo_suelo=self.suelo1,
        )
        Lote.objects.create(
            codigo="L2",
            nombre="Lote 2",
            superficie_ha=80,
            max_cultivos_principales=2,
            max_cultivos_secundarios=1,
            tipo_suelo=self.suelo1,
        )
        for codigo in (
            "fsp", "sc", "hc", "frc", "vr", "tf",
            "scp", "cp", "st", "cst", "clt",
        ):
            TipoCosto.objects.create(codigo=codigo, descripcion=codigo)

    def test_cultivo_create_and_list(self):
        base_year = datetime.now().year
        data = {
            "codigo": "GIRASOL",
            "nombre": "Girasol Hibrido",
            "tipo": "principal",
            "duracion_dias": "110",
            "siembra_inicio_fecha": f"{base_year}-06-15",
            "siembra_fin_fecha": f"{base_year}-08-24",
            "no_repetir_sin_intermedio": "on",
            f"rendimiento_{self.suelo1.id}": "3.8"
        }
        request = self.factory.post('/cultivos/crear/', data)
        request.user = self.user
        
        # Mock messages framework
        from django.contrib.messages.storage.base import BaseStorage
        class DummyStorage(BaseStorage):
            def _get(self):
                return [], True
            def _store(self, messages, response, *args, **kwargs):
                return []
        setattr(request, '_messages', DummyStorage(request))

        response = cultivo_create(request)
        self.assertEqual(response.status_code, 200)

        # Verify DB entries
        cultivo_obj = Cultivo.objects.get(codigo="GIRASOL")
        self.assertEqual(cultivo_obj.nombre, "Girasol Hibrido")
        self.assertEqual(cultivo_obj.tipo, Cultivo.Tipo.PRINCIPAL)
        self.assertEqual(cultivo_obj.duracion_dias, 110)
        self.assertEqual(cultivo_obj.siembra_inicio, 15)
        self.assertEqual(cultivo_obj.siembra_fin, 85)
        self.assertTrue(cultivo_obj.no_repetir_sin_intermedio)
        self.assertFalse(cultivo_obj.habilitado_optimizacion)

        # Verify yields and compatibilities
        rend = RendimientoCultivoSuelo.objects.get(cultivo=cultivo_obj, tipo_suelo=self.suelo1)
        self.assertEqual(rend.valor, 3.8)
        compat = CompatibilidadCultivoSuelo.objects.get(cultivo=cultivo_obj, tipo_suelo=self.suelo1)
        self.assertTrue(compat.compatible)

        costos = Costo.objects.filter(cultivo=cultivo_obj)
        self.assertEqual(costos.count(), 23)
        self.assertFalse(costos.filter(configurado=True).exists())
        self.assertEqual(
            costos.filter(tipo_costo__codigo="fsp", campania__isnull=False).count(),
            2,
        )
        self.assertEqual(
            costos.filter(
                tipo_costo__codigo="frc",
                campania__isnull=False,
                lote__isnull=False,
            ).count(),
            4,
        )

        # Verify rendered HTML
        html = response.content.decode('utf-8')
        self.assertIn("GIRASOL", html)
        self.assertTrue("3.8" in html or "3,8" in html)


class CostoListDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.factory = RequestFactory()
        self.cultivo = Cultivo.objects.create(
            codigo="SOJA_TEST",
            nombre="Soja Test",
            tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120,
            siembra_inicio=10,
            siembra_fin=90,
        )
        self.tipo_costo = TipoCosto.objects.create(
            codigo="fsp",
            descripcion="Future selling price",
            unidad="USD/ton",
        )
        self.campania = Campania.objects.create(codigo="C1", orden=1)
        self.costo = Costo.objects.create(
            cultivo=self.cultivo,
            tipo_costo=self.tipo_costo,
            campania=self.campania,
            valor=320.0,
        )

    def test_costo_list_updates_values(self):
        request = self.factory.post('/costos/', {f"costo_{self.costo.id}": "355.50"})
        request.user = self.user

        from django.contrib.messages.storage.base import BaseStorage
        class DummyStorage(BaseStorage):
            def _get(self):
                return [], True
            def _store(self, messages, response, *args, **kwargs):
                return []
        setattr(request, '_messages', DummyStorage(request))

        response = costo_list(request)
        self.assertEqual(response.status_code, 200)

        self.costo.refresh_from_db()
        self.assertEqual(self.costo.valor, 355.5)

        html = response.content.decode('utf-8')
        self.assertIn("SOJA_TEST", html)
        self.assertIn("fsp", html)

    def test_costo_list_paginates_values(self):
        for index in range(55):
            cultivo = Cultivo.objects.create(
                codigo=f"MAIZ_{index}",
                nombre=f"Maiz {index}",
                tipo=Cultivo.Tipo.PRINCIPAL,
                duracion_dias=120,
                siembra_inicio=10,
                siembra_fin=90,
            )
            Costo.objects.create(
                cultivo=cultivo,
                tipo_costo=self.tipo_costo,
                campania=self.campania,
                valor=300.0 + index,
            )

        request = self.factory.get('/costos/')
        request.user = self.user

        response = costo_list(request)
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')
        self.assertIn("Página 1 de 8", html)
        self.assertIn("Siguiente", html)

    def test_costo_list_hides_barbecho_in_filter_and_table(self):
        barbecho = Cultivo.objects.create(
            codigo="BARBECHO",
            nombre="Barbecho",
            tipo=Cultivo.Tipo.OTRO,
            duracion_dias=30,
            siembra_inicio=1,
            siembra_fin=30,
        )
        Costo.objects.create(
            cultivo=barbecho,
            tipo_costo=self.tipo_costo,
            campania=self.campania,
            valor=0,
        )

        request = self.factory.get("/costos/")
        request.user = self.user

        response = costo_list(request)
        self.assertEqual(response.status_code, 200)

        html = response.content.decode("utf-8")
        self.assertNotIn('option value="%s"' % barbecho.id, html)
        self.assertNotIn("BARBECHO", html)

    def test_enables_crop_after_all_costs_are_reviewed(self):
        self.cultivo.habilitado_optimizacion = False
        self.cultivo.save(update_fields=["habilitado_optimizacion"])
        self.costo.configurado = False
        self.costo.save(update_fields=["configurado"])

        request = self.factory.post(
            f'/costos/?cultivo={self.cultivo.id}',
            {
                f"costo_{self.costo.id}": "0",
                "action": "enable",
            },
        )
        request.user = self.user

        from django.contrib.messages.storage.base import BaseStorage
        class DummyStorage(BaseStorage):
            def _get(self):
                return [], True
            def _store(self, messages, response, *args, **kwargs):
                return []
        setattr(request, '_messages', DummyStorage(request))

        response = costo_list(request)
        self.assertEqual(response.status_code, 200)

        self.cultivo.refresh_from_db()
        self.costo.refresh_from_db()
        self.assertTrue(self.costo.configurado)
        self.assertTrue(self.cultivo.habilitado_optimizacion)


class EjecutarOptimizacionDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
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


class ProcessOptimizationsCommandTest(TestCase):
    @patch("core.management.commands.process_optimizations.run_optimization")
    def test_solver_failure_is_not_reported_as_success(self, run_optimization_mock):
        planificacion = Planificacion.objects.create(nombre="Planificacion fallida")
        run_optimization_mock.return_value = False
        command = ProcessOptimizationsCommand(stdout=StringIO(), stderr=StringIO())

        processed = command._process_one()

        self.assertFalse(processed)
        run_optimization_mock.assert_called_once_with(planificacion.id)
        self.assertIn("termino con error", command.stderr.getvalue())
        self.assertNotIn("finalizada", command.stdout.getvalue())


class OptimizationInputsTest(TestCase):
    def test_excludes_crops_pending_economic_configuration(self):
        Cultivo.objects.create(
            codigo="HABILITADO",
            nombre="Habilitado",
            tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=100,
            siembra_inicio=1,
            siembra_fin=30,
            habilitado_optimizacion=True,
        )
        Cultivo.objects.create(
            codigo="BORRADOR",
            nombre="Borrador",
            tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=100,
            siembra_inicio=1,
            siembra_fin=30,
            habilitado_optimizacion=False,
        )

        data = build_pyomo_input_data()

        self.assertIn("HABILITADO", data["i"])
        self.assertNotIn("BORRADOR", data["i"])


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
