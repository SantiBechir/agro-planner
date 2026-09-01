from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import EDITOR_ROLE, READER_ROLE, set_functional_role
from core.models import (
    Ambiente,
    Campania,
    CampaniaHistorica,
    Costo,
    Cultivo,
    HistorialLoteCultivo,
    Lote,
    Planificacion,
    TipoCosto,
    TipoSuelo,
)


User = get_user_model()


class RoleAuthorizationTest(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user(
            email="editor@example.com",
            first_name="Elena",
            last_name="Editora",
            password="password",
        )
        self.reader = User.objects.create_user(
            email="lector@example.com",
            first_name="Leo",
            last_name="Lector",
            password="password",
        )
        set_functional_role(self.editor, EDITOR_ROLE)
        set_functional_role(self.reader, READER_ROLE)

        self.soil = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        self.campaign = Campania.objects.create(codigo="C1", orden=1)
        self.lot = Lote.objects.create(
            codigo="J1",
            nombre="Parcela Norte",
            superficie_ha=100,
            max_cultivos_principales=10,
            max_cultivos_secundarios=10,
            tipo_suelo=self.soil,
        )
        Ambiente.objects.create(
            lote=self.lot,
            tipo_suelo=self.soil,
            rendimiento_esperado="M",
            superficie_ha=100,
        )
        self.crop = Cultivo.objects.create(
            codigo="TRIGO",
            nombre="Trigo",
            tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120,
            siembra_inicio=10,
            siembra_fin=90,
        )
        historical_campaign = CampaniaHistorica.objects.create(
            codigo="CH2024", anio_inicio=2024
        )
        HistorialLoteCultivo.objects.create(
            lote=self.lot,
            cultivo=self.crop,
            campania_historica=historical_campaign,
        )
        self.cost_type = TipoCosto.objects.create(
            codigo="fsp", descripcion="Precio", unidad="USD/t"
        )
        self.cost = Costo.objects.create(
            cultivo=self.crop,
            tipo_costo=self.cost_type,
            campania=self.campaign,
            valor=300,
        )

    def _lot_data(self, name="Parcela Norte"):
        return {
            "nombre": name,
            "suelo_0": str(self.soil.pk),
            "rendimiento_0": "M",
            "ha_0": "100",
            "habilitado": "1",
        }

    def _crop_data(self):
        year = datetime.now().year
        return {
            "nombre": "Girasol",
            "tipo": Cultivo.Tipo.PRINCIPAL,
            "duracion_dias": "100",
            "siembra_inicio_fecha": f"{year}-06-10",
            "siembra_fin_fecha": f"{year}-08-10",
            f"rendimiento_{self.soil.pk}": "3.5",
        }

    def test_reader_receives_403_on_every_agricultural_write_without_changes(self):
        self.client.force_login(self.reader)
        initial = {
            "lots": Lote.objects.count(),
            "crops": Cultivo.objects.count(),
            "history": HistorialLoteCultivo.objects.count(),
            "name": self.lot.nombre,
            "enabled": self.lot.habilitado,
            "cost": self.cost.valor,
        }
        requests = (
            ("post", reverse("lote_create"), self._lot_data("Nueva Parcela")),
            ("post", reverse("lote_update", args=[self.lot.pk]), self._lot_data("Alterado")),
            ("post", reverse("lote_toggle", args=[self.lot.pk]), {}),
            ("post", reverse("lote_historial_add", args=[self.lot.pk]), {"anio_inicio": "2023", "cultivo_1": self.crop.pk}),
            ("post", reverse("lote_historial_delete", args=[self.lot.pk, 2024]), {}),
            ("post", reverse("cultivo_create"), self._crop_data()),
            ("post", reverse("costo_list"), {f"costo_{self.cost.pk}": "999"}),
        )
        for method, url, data in requests:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url, data)
                self.assertEqual(response.status_code, 403)

        self.lot.refresh_from_db()
        self.cost.refresh_from_db()
        self.assertEqual(Lote.objects.count(), initial["lots"])
        self.assertEqual(Cultivo.objects.count(), initial["crops"])
        self.assertEqual(HistorialLoteCultivo.objects.count(), initial["history"])
        self.assertEqual(self.lot.nombre, initial["name"])
        self.assertEqual(self.lot.habilitado, initial["enabled"])
        self.assertEqual(self.cost.valor, initial["cost"])

    def test_editor_can_use_every_agricultural_write_family(self):
        self.client.force_login(self.editor)

        self.assertEqual(
            self.client.post(reverse("lote_create"), self._lot_data("Parcela Sur")).status_code,
            200,
        )
        self.assertTrue(Lote.objects.filter(nombre="Parcela Sur").exists())

        self.assertEqual(
            self.client.post(
                reverse("lote_update", args=[self.lot.pk]),
                self._lot_data("Parcela Actualizada"),
            ).status_code,
            200,
        )
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.nombre, "Parcela Actualizada")

        self.assertEqual(
            self.client.post(reverse("lote_toggle", args=[self.lot.pk])).status_code,
            200,
        )
        self.lot.refresh_from_db()
        self.assertFalse(self.lot.habilitado)

        self.assertEqual(
            self.client.post(
                reverse("lote_historial_add", args=[self.lot.pk]),
                {"anio_inicio": "2023", "cultivo_1": self.crop.pk},
            ).status_code,
            200,
        )
        self.assertTrue(
            HistorialLoteCultivo.objects.filter(
                lote=self.lot, campania_historica__anio_inicio=2023
            ).exists()
        )
        self.assertEqual(
            self.client.post(
                reverse("lote_historial_delete", args=[self.lot.pk, 2024])
            ).status_code,
            200,
        )
        self.assertFalse(
            HistorialLoteCultivo.objects.filter(
                lote=self.lot, campania_historica__anio_inicio=2024
            ).exists()
        )

        self.assertEqual(
            self.client.post(reverse("cultivo_create"), self._crop_data()).status_code,
            200,
        )
        self.assertTrue(Cultivo.objects.filter(codigo="GIRASOL").exists())

        self.assertEqual(
            self.client.post(
                reverse("costo_list"), {f"costo_{self.cost.pk}": "350"}
            ).status_code,
            200,
        )
        self.cost.refresh_from_db()
        self.assertEqual(self.cost.valor, 350)

    def test_mutation_only_endpoints_reject_get(self):
        self.client.force_login(self.editor)
        urls = (
            reverse("lote_create"),
            reverse("lote_update", args=[self.lot.pk]),
            reverse("lote_toggle", args=[self.lot.pk]),
            reverse("lote_historial_add", args=[self.lot.pk]),
            reverse("lote_historial_delete", args=[self.lot.pk, 2024]),
            reverse("cultivo_create"),
            reverse("ejecutar_optimizacion"),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_both_roles_can_read_global_data_and_create_pending_plans(self):
        read_urls = (
            reverse("home"),
            reverse("lote_list"),
            reverse("cultivo_list"),
            reverse("costo_list"),
            reverse("planificacion_list"),
        )
        for user in (self.editor, self.reader):
            self.client.force_login(user)
            for url in read_urls:
                with self.subTest(role=user.functional_role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
            response = self.client.post(
                reverse("ejecutar_optimizacion"),
                {"nombre": f"Plan {user.functional_role}"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(
                Planificacion.objects.filter(
                    nombre=f"Plan {user.functional_role}",
                    estado=Planificacion.Estado.PENDIENTE,
                ).exists()
            )

    def test_write_controls_are_visible_only_to_editor(self):
        expectations = (
            (reverse("lote_list"), "+ Agregar Lote"),
            (reverse("cultivo_list"), "+ Agregar Cultivo"),
        )
        for url, label in expectations:
            self.client.force_login(self.editor)
            editor_html = self.client.get(url).content.decode()
            self.assertIn(label, editor_html)

            self.client.force_login(self.reader)
            reader_html = self.client.get(url).content.decode()
            self.assertNotIn(label, reader_html)

        self.client.force_login(self.editor)
        editor_costs = self.client.get(reverse("costo_list")).content.decode()
        self.assertIn(f'name="costo_{self.cost.pk}"', editor_costs)
        self.assertIn("Guardar Cambios", editor_costs)

        self.client.force_login(self.reader)
        reader_costs = self.client.get(reverse("costo_list")).content.decode()
        self.assertNotIn(f'name="costo_{self.cost.pk}"', reader_costs)
        self.assertNotIn("Guardar Cambios", reader_costs)
        self.assertIn("Nueva Planificación", self.client.get(reverse("planificacion_list")).content.decode())

    def test_home_shows_real_role_and_superuser_bypasses_editor_group(self):
        self.client.force_login(self.reader)
        self.assertContains(self.client.get(reverse("home")), "LECTOR")

        superuser = User.objects.create_superuser(
            email="admin@example.com",
            first_name="Super",
            last_name="Usuario",
            password="password",
        )
        self.assertEqual(superuser.functional_role, "Superusuario")
        self.client.force_login(superuser)
        response = self.client.post(reverse("lote_toggle", args=[self.lot.pk]))
        self.assertEqual(response.status_code, 200)
