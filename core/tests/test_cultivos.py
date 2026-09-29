from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from core.views import cultivo_list, cultivo_create
from accounts.roles import EDITOR_ROLE, READER_ROLE, set_functional_role
from core.models import Cultivo, TipoSuelo, RendimientoCultivoSuelo, Lote, CompatibilidadCultivoSuelo, TipoCosto, Costo, Campania
from core.services.costos import COMPONENTES_SIEMBRA
from datetime import datetime, timedelta


User = get_user_model()


class CultivoListDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            password="password",
        )
        set_functional_role(self.user, READER_ROLE)
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
        self.assertIn("Habilitado", html)
        self.assertIn("De Renta", html)
        self.assertNotIn(">\n            Principal\n", html)

    def test_cultivo_list_requires_authentication(self):
        response = self.client.get("/cultivos/")

        self.assertRedirects(response, "/login/?next=/cultivos/")

    def test_cultivo_list_shows_disabled_optimization_status(self):
        self.cultivo.habilitado_optimizacion = False
        self.cultivo.save(update_fields=["habilitado_optimizacion"])

        request = self.factory.get('/cultivos/')
        request.user = self.user
        response = cultivo_list(request)

        html = response.content.decode('utf-8')
        self.assertIn("No habilitado", html)

    def test_economic_status_uses_pending_cost_count(self):
        tipo = TipoCosto.objects.create(codigo="sc", descripcion="Costo")
        Costo.objects.create(
            cultivo=self.cultivo,
            tipo_costo=tipo,
            valor=0,
            configurado=False,
        )

        request = self.factory.get('/cultivos/')
        request.user = self.user
        response = cultivo_list(request)

        html = response.content.decode('utf-8')
        self.assertIn("1 valor económico pendiente", html)
        self.assertNotIn("Pendiente de configuración económica", html)

    def test_barbecho_is_not_listed(self):
        Cultivo.objects.create(
            codigo="BARBECHO",
            nombre="Barbecho",
            tipo=Cultivo.Tipo.OTRO,
            duracion_dias=30,
            siembra_inicio=1,
            siembra_fin=30,
            habilitado_optimizacion=False,
        )

        request = self.factory.get('/cultivos/')
        request.user = self.user
        response = cultivo_list(request)

        html = response.content.decode('utf-8')
        self.assertNotIn(">\n            BARBECHO\n", html)


class CultivoCreateDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            password="password",
        )
        set_functional_role(self.user, EDITOR_ROLE)
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
            "fsp", *COMPONENTES_SIEMBRA, "hc", "frc", "vr", "tf",
            "scp", "cp", "st", "cst", "clt",
        ):
            TipoCosto.objects.create(codigo=codigo, descripcion=codigo)

    def test_cultivo_create_and_list(self):
        base_year = datetime.now().year
        data = {
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
        cultivo_obj = Cultivo.objects.get(codigo="GIRASOL HIBRIDO")
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
        self.assertEqual(costos.count(), 31)
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
