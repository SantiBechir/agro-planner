from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from core.views import costo_list
from accounts.roles import EDITOR_ROLE, set_functional_role
from core.models import Cultivo, TipoSuelo, Lote, TipoCosto, Costo, Campania
from core.services.costos import COMPONENTES_SIEMBRA


User = get_user_model()


class CostoListDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            password="password",
        )
        set_functional_role(self.user, EDITOR_ROLE)
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
        self.assertIn("Precio futuro de venta", html)

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

    def test_costo_list_excludes_barbecho(self):
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
            valor=10.0,
        )

        request = self.factory.get('/costos/')
        request.user = self.user

        response = costo_list(request)
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')
        self.assertIn("SOJA_TEST", html)
        self.assertNotIn("BARBECHO", html)
        self.assertNotIn("Barbecho", html)

    def test_rental_costs_are_rendered_in_separate_lot_table(self):
        suelo = TipoSuelo.objects.create(codigo="S1", nombre="Suelo 1")
        lote = Lote.objects.create(
            codigo="L1",
            nombre="Lote 1",
            superficie_ha=100,
            max_cultivos_principales=2,
            max_cultivos_secundarios=1,
            tipo_suelo=suelo,
        )
        costo_cultivo = TipoCosto.objects.create(
            codigo="sc_seed",
            descripcion="Seed cost",
            unidad="USD/ha",
        )
        arrendamiento = TipoCosto.objects.create(
            codigo="frc",
            descripcion="Fixed rental cost",
            unidad="USD",
        )
        Costo.objects.create(
            cultivo=self.cultivo,
            tipo_costo=costo_cultivo,
            campania=self.campania,
            valor=120.0,
        )
        Costo.objects.create(
            cultivo=self.cultivo,
            tipo_costo=arrendamiento,
            campania=self.campania,
            lote=lote,
            valor=5000.0,
        )

        request = self.factory.get('/costos/')
        request.user = self.user

        response = costo_list(request)
        self.assertEqual(response.status_code, 200)

        general_section = response.content.decode('utf-8').split(
            "Precios y costos generales", 1
        )[1]
        self.assertIn("Semillas", general_section)
        self.assertNotIn("Costo fijo de arrendamiento", general_section)
        self.assertNotIn("Lote</th>", general_section)

        request = self.factory.get(f'/costos/?tipo={arrendamiento.id}')
        request.user = self.user

        response = costo_list(request)
        self.assertEqual(response.status_code, 200)

        rental_section = response.content.decode('utf-8')

        self.assertNotIn("Precios y costos generales", rental_section)
        self.assertIn("Costo fijo de arrendamiento", rental_section)
        self.assertIn("Lote</th>", rental_section)
        self.assertIn("L1", rental_section)
        self.assertIn("Campaña", rental_section)

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

    def test_sowing_components_are_editable_and_total_is_read_only(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        for code, value in zip(COMPONENTES_SIEMBRA, values):
            cost_type = TipoCosto.objects.create(
                codigo=code, descripcion=code, unidad="USD/ha"
            )
            Costo.objects.create(
                cultivo=self.cultivo,
                tipo_costo=cost_type,
                campania=self.campania,
                valor=value,
            )

        request = self.factory.get(f"/costos/?cultivo={self.cultivo.id}")
        request.user = self.user
        response = costo_list(request)
        html = response.content.decode("utf-8")

        self.assertIn("Costo total de siembra", html)
        self.assertIn("150", html)
        self.assertNotIn('name="costo_total_siembra"', html)
        for code in COMPONENTES_SIEMBRA:
            cost = Costo.objects.get(
                cultivo=self.cultivo, tipo_costo__codigo=code
            )
            self.assertIn(f'name="costo_{cost.id}"', html)
