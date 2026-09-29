from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from core.views import lote_list, lote_historial_add, lote_historial_delete
from accounts.roles import EDITOR_ROLE, set_functional_role
from core.models import Cultivo, TipoSuelo, Lote, CampaniaHistorica, HistorialLoteCultivo
from .support import RecordingMessages


User = get_user_model()


class LoteHistorialAddTest(TestCase):
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
        self.trigo = Cultivo.objects.create(
            codigo="TRIGO", nombre="Trigo", tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120, siembra_inicio=10, siembra_fin=90,
        )
        self.soja = Cultivo.objects.create(
            codigo="SOJA", nombre="Soja", tipo=Cultivo.Tipo.SECUNDARIO,
            duracion_dias=100, siembra_inicio=100, siembra_fin=200,
        )

    def _post_historial(self, data):
        request = self.factory.post(f'/lotes/{self.lote.id}/historial/', data)
        request.user = self.user
        request._messages = RecordingMessages()
        return lote_historial_add(request, pk=self.lote.id), request._messages

    def test_double_crop_creates_two_records_with_yields(self):
        response, _ = self._post_historial({
            "anio_inicio": "2024",
            "cultivo_1": str(self.trigo.id),
            "rendimiento_1": "3200",
            "cultivo_2": str(self.soja.id),
            "rendimiento_2": "2800",
        })
        self.assertEqual(response.status_code, 200)

        campania = CampaniaHistorica.objects.get(anio_inicio=2024)
        self.assertEqual(campania.codigo, "CH2024")
        registros = HistorialLoteCultivo.objects.filter(
            lote=self.lote, campania_historica=campania
        )
        self.assertEqual(registros.count(), 2)
        self.assertEqual(
            registros.get(cultivo=self.trigo).rendimiento_kg_ha, 3200.0
        )
        self.assertEqual(
            registros.get(cultivo=self.soja).rendimiento_kg_ha, 2800.0
        )

    def test_reload_same_campaign_updates_instead_of_duplicating(self):
        self._post_historial({
            "anio_inicio": "2024",
            "cultivo_1": str(self.trigo.id),
            "rendimiento_1": "3200",
        })
        self._post_historial({
            "anio_inicio": "2024",
            "cultivo_1": str(self.trigo.id),
            "rendimiento_1": "3500",
        })

        campania = CampaniaHistorica.objects.get(anio_inicio=2024)
        registros = HistorialLoteCultivo.objects.filter(
            lote=self.lote, campania_historica=campania, cultivo=self.trigo
        )
        self.assertEqual(registros.count(), 1)
        self.assertEqual(registros.get().rendimiento_kg_ha, 3500.0)

    def test_replacing_double_crop_with_single_crop_removes_second_crop(self):
        self._post_historial({
            "anio_inicio": "2024", "cultivo_1": str(self.trigo.id),
            "rendimiento_1": "3200", "cultivo_2": str(self.soja.id),
            "rendimiento_2": "2800",
        })
        self._post_historial({
            "anio_inicio": "2024", "cultivo_1": str(self.trigo.id),
            "rendimiento_1": "3500",
        })
        registros = HistorialLoteCultivo.objects.filter(
            lote=self.lote, campania_historica__anio_inicio=2024
        )
        self.assertEqual(registros.count(), 1)
        self.assertEqual(registros.get().cultivo, self.trigo)
        self.assertEqual(registros.get().rendimiento_kg_ha, 3500)

    def test_delete_history_removes_only_selected_lote_and_campaign(self):
        otra_lote = Lote.objects.create(
            codigo="J2", nombre="Otra parcela", superficie_ha=20,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=self.suelo1,
        )
        for anio in (2024, 2023):
            campania = CampaniaHistorica.objects.create(
                codigo=f"CH{anio}", anio_inicio=anio
            )
            HistorialLoteCultivo.objects.create(
                lote=self.lote, cultivo=self.trigo, campania_historica=campania
            )
            if anio == 2024:
                HistorialLoteCultivo.objects.create(
                    lote=self.lote, cultivo=self.soja, campania_historica=campania
                )
        HistorialLoteCultivo.objects.create(
            lote=otra_lote, cultivo=self.trigo,
            campania_historica=CampaniaHistorica.objects.get(anio_inicio=2024),
        )
        request = self.factory.post(f"/lotes/{self.lote.id}/historial/2024/eliminar/")
        request.user = self.user
        request._messages = RecordingMessages()
        response = lote_historial_delete(request, pk=self.lote.id, anio_inicio=2024)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HistorialLoteCultivo.objects.filter(
            lote=self.lote, campania_historica__anio_inicio=2024
        ).exists())
        self.assertTrue(HistorialLoteCultivo.objects.filter(
            lote=self.lote, campania_historica__anio_inicio=2023
        ).exists())
        self.assertTrue(HistorialLoteCultivo.objects.filter(
            lote=otra_lote, campania_historica__anio_inicio=2024
        ).exists())

    def test_loading_same_year_twice_creates_single_campania(self):
        self._post_historial({
            "anio_inicio": "2020",
            "cultivo_1": str(self.trigo.id),
        })
        self._post_historial({
            "anio_inicio": "2020",
            "cultivo_1": str(self.soja.id),
        })
        self.assertEqual(
            CampaniaHistorica.objects.filter(anio_inicio=2020).count(), 1
        )
        self.assertEqual(CampaniaHistorica.objects.count(), 1)

    def test_same_crop_twice_is_rejected(self):
        response, msgs = self._post_historial({
            "anio_inicio": "2024",
            "cultivo_1": str(self.trigo.id),
            "cultivo_2": str(self.trigo.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("distinto del primero", msgs.text())
        self.assertFalse(HistorialLoteCultivo.objects.exists())

    def test_current_or_future_campaign_is_rejected(self):
        for anio in ("2025", "2026"):
            response, msgs = self._post_historial({
                "anio_inicio": anio,
                "cultivo_1": str(self.trigo.id),
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn("anterior a la campaña actual", msgs.text())
        self.assertFalse(HistorialLoteCultivo.objects.exists())
        self.assertFalse(CampaniaHistorica.objects.exists())

    def test_campaign_older_than_load_window_is_rejected(self):
        response, msgs = self._post_historial({
            "anio_inicio": "2009",
            "cultivo_1": str(self.trigo.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("últimas 15 campañas", msgs.text())
        self.assertFalse(HistorialLoteCultivo.objects.exists())
        self.assertFalse(CampaniaHistorica.objects.exists())

    def test_non_integer_year_is_rejected(self):
        response, msgs = self._post_historial({
            "anio_inicio": "abc",
            "cultivo_1": str(self.trigo.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("campaña y el cultivo principal", msgs.text())
        self.assertFalse(HistorialLoteCultivo.objects.exists())

    def test_old_year_within_window_loads_and_displays(self):
        response, _ = self._post_historial({
            "anio_inicio": "2015",
            "cultivo_1": str(self.trigo.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            CampaniaHistorica.objects.filter(anio_inicio=2015).exists()
        )
        html = response.content.decode("utf-8")
        self.assertIn("2015/2016", html)


class LoteListHistorialGroupingTest(TestCase):
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
        self.ch1 = CampaniaHistorica.objects.create(codigo="CH1", anio_inicio=2024)
        self.ch2 = CampaniaHistorica.objects.create(codigo="CH2", anio_inicio=2023)
        self.trigo = Cultivo.objects.create(
            codigo="TRIGO", nombre="Trigo", tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120, siembra_inicio=10, siembra_fin=90,
        )
        self.soja = Cultivo.objects.create(
            codigo="SOJA", nombre="Soja", tipo=Cultivo.Tipo.SECUNDARIO,
            duracion_dias=100, siembra_inicio=100, siembra_fin=200,
        )

    def _get_lotes_html(self):
        request = self.factory.get('/lotes/')
        request.user = self.user
        response = lote_list(request)
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    def test_history_grouped_one_row_per_campaign_most_recent_first(self):
        # 2024/2025 (most recent) holds a double crop; 2023/2024 single crop
        HistorialLoteCultivo.objects.create(
            lote=self.lote, cultivo=self.trigo,
            campania_historica=self.ch1, rendimiento_kg_ha=3200,
        )
        HistorialLoteCultivo.objects.create(
            lote=self.lote, cultivo=self.soja,
            campania_historica=self.ch1, rendimiento_kg_ha=2800,
        )
        HistorialLoteCultivo.objects.create(
            lote=self.lote, cultivo=self.trigo,
            campania_historica=self.ch2,
        )
        vieja = CampaniaHistorica.objects.create(codigo="CH2018", anio_inicio=2018)
        HistorialLoteCultivo.objects.create(
            lote=self.lote, cultivo=self.trigo,
            campania_historica=vieja,
        )

        html = self._get_lotes_html()

        # History rows render most recent first: 2024/2025, 2023/2024, 2018/2019
        self.assertLess(html.index("2024/2025"), html.index("2023/2024"))
        self.assertLess(html.index("2023/2024"), html.index("2018/2019"))
        # Internal CH codes must not appear in producer-facing HTML
        self.assertNotIn("CH2018", html)
        # Double crop shares the same campaign row, with yields shown
        self.assertIn("TRIGO (3200 kg/ha)", html)
        self.assertIn("SOJA (2800 kg/ha)", html)
        # Campaign without yield shows just the crop name
        self.assertNotIn("(None kg/ha)", html)

    def test_free_year_select_offers_last_15_campaigns(self):
        html = self._get_lotes_html()

        # Options from 2024/2025 down to 2010/2011 (base fallback is 2025)
        self.assertIn('value="2024"', html)
        self.assertIn("2024/2025", html)
        self.assertIn('value="2010"', html)
        self.assertIn("2010/2011", html)
        self.assertNotIn('value="2025"', html)
        self.assertNotIn('value="2009"', html)
        # Muted caption about the model window
        self.assertIn("El modelo considera las 3 campañas más recientes.", html)

    def test_markup_includes_lote_and_campaign_edit_actions(self):
        HistorialLoteCultivo.objects.create(
            lote=self.lote, cultivo=self.trigo, campania_historica=self.ch1,
            rendimiento_kg_ha=3200,
        )
        html = self._get_lotes_html()
        self.assertIn("Editar lote", html)
        self.assertIn(f'/lotes/{self.lote.id}/editar/', html)
        self.assertIn("Editar campaña", html)
        self.assertIn(f'/lotes/{self.lote.id}/historial/2024/eliminar/', html)
