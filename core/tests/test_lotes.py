from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from core.views import lote_create, lote_update, lote_toggle
from accounts.roles import EDITOR_ROLE, set_functional_role
from core.models import Ambiente, TipoSuelo, Lote
from .support import RecordingMessages


User = get_user_model()


class LoteCreateDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            password="password",
        )
        set_functional_role(self.user, EDITOR_ROLE)
        self.factory = RequestFactory()
        self.suelo1 = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        self.suelo2 = TipoSuelo.objects.create(codigo="S2", nombre="Alfisol")

    def _post_create(self, data):
        request = self.factory.post('/lotes/crear/', data)
        request.user = self.user
        request._messages = RecordingMessages()
        return lote_create(request), request._messages

    def _create_lote(self, codigo="JX", nombre="Lote X", **kwargs):
        defaults = {
            "superficie_ha": 100,
            "max_cultivos_principales": 10,
            "max_cultivos_secundarios": 10,
            "tipo_suelo": self.suelo1,
        }
        defaults.update(kwargs)
        return Lote.objects.create(codigo=codigo, nombre=nombre, **defaults)

    def test_lote_create_and_list(self):
        data = {
            "nombre": "Parcela Norte",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "A",
            "ha_0": "250.5",
        }
        response, _ = self._post_create(data)
        self.assertEqual(response.status_code, 200)

        # Verify DB entry: auto codigo, defaults and dominant soil bridge
        lote_obj = Lote.objects.get(nombre="Parcela Norte")
        self.assertEqual(lote_obj.codigo, "J1")
        self.assertEqual(lote_obj.superficie_ha, 250.5)
        self.assertEqual(lote_obj.max_cultivos_principales, 10)
        self.assertEqual(lote_obj.max_cultivos_secundarios, 10)
        self.assertEqual(lote_obj.tipo_suelo, self.suelo1)
        self.assertTrue(lote_obj.habilitado)

        # Verify ambiente was created
        ambiente = Ambiente.objects.get(lote=lote_obj)
        self.assertEqual(ambiente.tipo_suelo, self.suelo1)
        self.assertEqual(ambiente.rendimiento_esperado, "A")
        self.assertEqual(ambiente.superficie_ha, 250.5)

        # Verify rendered HTML
        html = response.content.decode('utf-8')
        self.assertIn("Parcela Norte", html)
        self.assertIn("Suelo Molisol", html)

    def test_auto_codigo_increments_from_highest_j_code(self):
        self._create_lote(codigo="J10", nombre="Lote J10")
        self._create_lote(codigo="LOTE_LIBRE", nombre="Lote libre")

        response, _ = self._post_create({
            "nombre": "Parcela Nueva",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "M",
            "ha_0": "40",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Lote.objects.filter(codigo="J11", nombre="Parcela Nueva").exists())

    def test_duplicate_nombre_rejected_case_insensitively(self):
        self._create_lote(codigo="J1", nombre="Parcela Norte")

        response, _ = self._post_create({
            "nombre": "parcela norte",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "M",
            "ha_0": "40",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'Ya existe un lote con el nombre "parcela norte"',
            response.content.decode("utf-8").replace("&quot;", '"'),
        )
        self.assertEqual(Lote.objects.count(), 1)

    def test_duplicate_nombre_reopens_modal_and_preserves_ambientes(self):
        existing = self._create_lote(codigo="J1", nombre="Parcela Norte")
        Ambiente.objects.create(
            lote=existing,
            tipo_suelo=self.suelo1,
            rendimiento_esperado="A",
            superficie_ha=100,
        )

        response, _ = self._post_create({
            "nombre": "parcela norte",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "M",
            "ha_0": "40.5",
            "suelo_1": str(self.suelo2.id),
            "rendimiento_1": "B",
            "ha_1": "60",
        })

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('role="alert"', html)
        self.assertIn(
            'Ya existe un lote con el nombre "parcela norte"',
            html.replace("&quot;", '"'),
        )
        self.assertIn("showModal: true", html)
        self.assertIn("nombreLote: 'parcela norte'", html)
        self.assertIn(f"sueloSel: ['{self.suelo1.id}', '{self.suelo2.id}']", html)
        self.assertIn("rendimientoSel: ['M', 'B']", html)
        self.assertIn("haSel: ['40.5', '60']", html)
        self.assertEqual(Lote.objects.count(), 1)
        self.assertEqual(Ambiente.objects.count(), 1)

    def test_create_with_two_ambientes_sets_sum_and_dominant_soil(self):
        response, _ = self._post_create({
            "nombre": "Parcela Mixta",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "A",
            "ha_0": "30",
            "suelo_1": str(self.suelo2.id),
            "rendimiento_1": "B",
            "ha_1": "70",
        })
        self.assertEqual(response.status_code, 200)

        lote_obj = Lote.objects.get(nombre="Parcela Mixta")
        self.assertEqual(lote_obj.superficie_ha, 100.0)
        self.assertEqual(lote_obj.tipo_suelo, self.suelo2)
        self.assertEqual(lote_obj.ambientes.count(), 2)

    def test_create_without_ambientes_is_rejected(self):
        response, _ = self._post_create({"nombre": "Parcela Sin Ambientes"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("al menos un ambiente", response.content.decode("utf-8"))
        self.assertFalse(Lote.objects.exists())

    def test_create_with_repeated_soil_is_rejected(self):
        response, _ = self._post_create({
            "nombre": "Parcela Repetida",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "A",
            "ha_0": "30",
            "suelo_1": str(self.suelo1.id),
            "rendimiento_1": "M",
            "ha_1": "70",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("repetir el mismo tipo de suelo", response.content.decode("utf-8"))
        self.assertFalse(Lote.objects.exists())

    def test_invalid_ambiente_reopens_modal_and_preserves_submitted_values(self):
        response, _ = self._post_create({
            "nombre": "Parcela Repetida",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "A",
            "ha_0": "30",
            "suelo_1": str(self.suelo1.id),
            "rendimiento_1": "M",
            "ha_1": "70",
        })

        html = response.content.decode("utf-8")
        self.assertIn("No puede repetir el mismo tipo de suelo", html)
        self.assertIn("showModal: true", html)
        self.assertIn("nombreLote: 'Parcela Repetida'", html)
        self.assertIn(f"sueloSel: ['{self.suelo1.id}', '{self.suelo1.id}']", html)
        self.assertIn("rendimientoSel: ['A', 'M']", html)
        self.assertIn("haSel: ['30', '70']", html)
        self.assertFalse(Lote.objects.exists())

    def test_create_with_non_positive_superficie_is_rejected(self):
        for ha_value in ("0", "-5", "abc"):
            response, _ = self._post_create({
                "nombre": f"Parcela {ha_value}",
                "suelo_0": str(self.suelo1.id),
                "rendimiento_0": "A",
                "ha_0": ha_value,
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn("mayor a cero", response.content.decode("utf-8"))
        self.assertFalse(Lote.objects.exists())

    def test_create_with_invalid_rendimiento_is_rejected(self):
        response, _ = self._post_create({
            "nombre": "Parcela Rinde",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "X",
            "ha_0": "30",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alto, Medio o Bajo", response.content.decode("utf-8"))
        self.assertFalse(Lote.objects.exists())


class LoteToggleTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            password="password",
        )
        set_functional_role(self.user, EDITOR_ROLE)
        self.factory = RequestFactory()
        self.suelo1 = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        self.lote = Lote.objects.create(
            codigo="J1",
            nombre="Parcela Norte",
            superficie_ha=100,
            max_cultivos_principales=10,
            max_cultivos_secundarios=10,
            tipo_suelo=self.suelo1,
        )

    def test_toggle_flips_habilitado(self):
        request = self.factory.post(f'/lotes/{self.lote.id}/toggle/')
        request.user = self.user
        request._messages = RecordingMessages()

        response = lote_toggle(request, pk=self.lote.id)
        self.assertEqual(response.status_code, 200)
        self.lote.refresh_from_db()
        self.assertFalse(self.lote.habilitado)

        request = self.factory.post(f'/lotes/{self.lote.id}/toggle/')
        request.user = self.user
        request._messages = RecordingMessages()

        lote_toggle(request, pk=self.lote.id)
        self.lote.refresh_from_db()
        self.assertTrue(self.lote.habilitado)


class LoteUpdateDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            first_name="Test",
            last_name="User",
            password="password",
        )
        set_functional_role(self.user, EDITOR_ROLE)
        self.factory = RequestFactory()
        self.suelo1 = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        self.suelo2 = TipoSuelo.objects.create(codigo="S2", nombre="Alfisol")
        self.lote = Lote.objects.create(
            codigo="J1", nombre="Parcela Norte", superficie_ha=100,
            max_cultivos_principales=7, max_cultivos_secundarios=4,
            tipo_suelo=self.suelo1, habilitado=True,
        )
        Ambiente.objects.create(
            lote=self.lote, tipo_suelo=self.suelo1,
            rendimiento_esperado="A", superficie_ha=100,
        )

    def _post_update(self, data):
        request = self.factory.post(f"/lotes/{self.lote.id}/editar/", data)
        request.user = self.user
        request._messages = RecordingMessages()
        return lote_update(request, pk=self.lote.id), request._messages

    def test_update_changes_producer_fields_and_preserves_internal_fields(self):
        response, _ = self._post_update({
            "nombre": "Parcela Mixta",
            "suelo_0": str(self.suelo1.id), "rendimiento_0": "B", "ha_0": "30",
            "suelo_1": str(self.suelo2.id), "rendimiento_1": "M", "ha_1": "70",
        })
        self.assertEqual(response.status_code, 200)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.nombre, "Parcela Mixta")
        self.assertFalse(self.lote.habilitado)
        self.assertEqual(self.lote.superficie_ha, 100)
        self.assertEqual(self.lote.tipo_suelo, self.suelo2)
        self.assertEqual(self.lote.codigo, "J1")
        self.assertEqual(self.lote.max_cultivos_principales, 7)
        self.assertEqual(self.lote.max_cultivos_secundarios, 4)
        self.assertEqual(self.lote.ambientes.count(), 2)

    def test_same_name_succeeds_but_another_lote_case_insensitive_duplicate_is_rejected(self):
        self._post_update({
            "nombre": "Parcela Norte", "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "M", "ha_0": "80",
        })
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.superficie_ha, 80)

        otro = Lote.objects.create(
            codigo="J2", nombre="Otra parcela", superficie_ha=20,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=self.suelo2,
        )
        response, msgs = self._post_update({
            "nombre": "OTRA PARCELA", "suelo_0": str(self.suelo2.id),
            "rendimiento_0": "A", "ha_0": "90",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ya existe un lote", msgs.text())
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.nombre, "Parcela Norte")
        self.assertEqual(self.lote.superficie_ha, 80)
        self.assertTrue(Lote.objects.filter(pk=otro.pk).exists())

    def test_invalid_ambiente_does_not_partially_update_lote_or_ambientes(self):
        response, msgs = self._post_update({
            "nombre": "Nombre no guardado", "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "X", "ha_0": "0",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alto, Medio o Bajo", msgs.text())
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.nombre, "Parcela Norte")
        ambiente = self.lote.ambientes.get()
        self.assertEqual(ambiente.rendimiento_esperado, "A")
        self.assertEqual(ambiente.superficie_ha, 100)
