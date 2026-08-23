from django.test import TestCase, RequestFactory
from django.conf import settings
from django.contrib.auth.models import User
from io import StringIO
from unittest.mock import patch
from core.views import cultivo_list, lote_list, lote_create, lote_update, lote_toggle, lote_historial_add, lote_historial_delete, cultivo_create, costo_list, ejecutar_optimizacion
from core.models import Ambiente, Cultivo, TipoSuelo, RendimientoCultivoSuelo, Lote, CompatibilidadCultivoSuelo, TipoCosto, Costo, Campania, CampaniaHistorica, HistorialLoteCultivo, Planificacion
from core.management.commands.process_optimizations import Command as ProcessOptimizationsCommand
from core.management.commands.cargar_input import (
    Command as CargarInputCommand,
    campania_historica_desde_columna_excel,
)
from core.management.commands.deploy_release import Command as DeployReleaseCommand
from core.services.optimization_inputs import build_pyomo_input_data
from django.template.loader import render_to_string
from datetime import date, datetime, timedelta


class RecordingMessages:
    """Minimal messages-framework stand-in that records added messages."""

    def __init__(self):
        self.recorded = []

    def add(self, level, message, extra_tags=""):
        self.recorded.append((level, message))

    def __iter__(self):
        from django.contrib.messages.storage.base import Message
        return iter([Message(level, message) for level, message in self.recorded])

    def __len__(self):
        return len(self.recorded)

    def text(self):
        return " | ".join(str(message) for _, message in self.recorded)

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
        self.assertIn("Habilitado", html)

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

    def test_barbecho_does_not_request_economic_configuration(self):
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
        self.assertEqual(html.count("Sin precios ni costos configurados"), 1)


class LoteCreateDirectTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
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

        response, msgs = self._post_create({
            "nombre": "parcela norte",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "M",
            "ha_0": "40",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('Ya existe un lote con el nombre "parcela norte"', msgs.text())
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
        response, msgs = self._post_create({"nombre": "Parcela Sin Ambientes"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("al menos un ambiente", msgs.text())
        self.assertFalse(Lote.objects.exists())

    def test_create_with_repeated_soil_is_rejected(self):
        response, msgs = self._post_create({
            "nombre": "Parcela Repetida",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "A",
            "ha_0": "30",
            "suelo_1": str(self.suelo1.id),
            "rendimiento_1": "M",
            "ha_1": "70",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("repetir el mismo tipo de suelo", msgs.text())
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
            response, msgs = self._post_create({
                "nombre": f"Parcela {ha_value}",
                "suelo_0": str(self.suelo1.id),
                "rendimiento_0": "A",
                "ha_0": ha_value,
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn("mayor a cero", msgs.text())
        self.assertFalse(Lote.objects.exists())

    def test_create_with_invalid_rendimiento_is_rejected(self):
        response, msgs = self._post_create({
            "nombre": "Parcela Rinde",
            "suelo_0": str(self.suelo1.id),
            "rendimiento_0": "X",
            "ha_0": "30",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alto, Medio o Bajo", msgs.text())
        self.assertFalse(Lote.objects.exists())


class LoteToggleTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
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
        self.user = User.objects.create_user(username="testuser", password="password")
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


class LoteHistorialAddTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
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
        self.user = User.objects.create_user(username="testuser", password="password")
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


class CampaniaHistoricaEtiquetaTest(TestCase):
    def test_etiqueta_comes_from_anio_inicio(self):
        ch = CampaniaHistorica.objects.create(codigo="CH2018", anio_inicio=2018)
        self.assertEqual(ch.etiqueta, "2018/2019")
        self.assertEqual(str(ch), "2018/2019")

        ch1 = CampaniaHistorica.objects.create(codigo="CH1", anio_inicio=2024)
        self.assertEqual(ch1.etiqueta, "2024/2025")

    def test_anio_base_actual_falls_back_to_module_constant(self):
        self.assertFalse(Campania.objects.exists())
        self.assertEqual(CampaniaHistorica.anio_base_actual(), 2025)

    def test_anio_base_actual_anchored_on_first_planning_campaign(self):
        Campania.objects.create(
            codigo="C1", orden=1, fecha_inicio=date(2025, 7, 1)
        )
        self.assertEqual(CampaniaHistorica.anio_base_actual(), 2025)


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
        self.assertIn("Pagina 1 de 8", html)
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
            codigo="sc",
            descripcion="Sowing cost",
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

        html = response.content.decode('utf-8')
        general_section = html.split("Costos generales", 1)[1].split(
            "Costos de arrendamiento", 1
        )[0]
        rental_section = html.split("Costos de arrendamiento", 1)[1]

        self.assertIn("Costo de cultivo", general_section)
        self.assertIn("no incluye el costo de arrendamiento", general_section)
        self.assertNotIn(">Lote</th>", general_section)
        self.assertIn("Costo fijo de arrendamiento", rental_section)
        self.assertIn(">Lote</th>", rental_section)
        self.assertIn("L1", rental_section)
        self.assertNotIn("Costo de siembra", html)
        self.assertNotIn("Que considera", html)
        self.assertIn("Campaña", html)

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

    def test_excludes_disabled_lotes_from_all_lote_params(self):
        suelo = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        activo = Lote.objects.create(
            codigo="J1", nombre="Activo", superficie_ha=100,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=True,
        )
        inactivo = Lote.objects.create(
            codigo="J2", nombre="Inactivo", superficie_ha=50,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=False,
        )
        cultivo = Cultivo.objects.create(
            codigo="TRIGO", nombre="Trigo", tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120, siembra_inicio=10, siembra_fin=90,
        )
        ch1 = CampaniaHistorica.objects.create(codigo="CH1", anio_inicio=2024)
        HistorialLoteCultivo.objects.create(
            lote=activo, cultivo=cultivo, campania_historica=ch1
        )
        HistorialLoteCultivo.objects.create(
            lote=inactivo, cultivo=cultivo, campania_historica=ch1
        )

        data = build_pyomo_input_data()

        self.assertIn("J1", data["j"])
        self.assertNotIn("J2", data["j"])
        for param in ("ha", "max_m", "max_s", "sueloj"):
            self.assertIn("J1", data[param])
            self.assertNotIn("J2", data[param])
        self.assertIn(("TRIGO", "J1", "CH1"), data["xh_dict"])
        self.assertNotIn(("TRIGO", "J2", "CH1"), data["xh_dict"])

    def _crear_lote_cultivo(self):
        suelo = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        lote = Lote.objects.create(
            codigo="J1", nombre="Activo", superficie_ha=100,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
            tipo_suelo=suelo, habilitado=True,
        )
        cultivo = Cultivo.objects.create(
            codigo="TRIGO", nombre="Trigo", tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120, siembra_inicio=10, siembra_fin=90,
        )
        return lote, cultivo

    def test_three_most_recent_campaigns_map_to_ch_codes(self):
        lote, cultivo = self._crear_lote_cultivo()
        # Base fallback is 2025 (no Campania rows): 2024→CH1, 2023→CH2, 2022→CH3
        for anio in (2024, 2023, 2022):
            campania = CampaniaHistorica.objects.create(
                codigo=f"CH{anio}", anio_inicio=anio
            )
            HistorialLoteCultivo.objects.create(
                lote=lote, cultivo=cultivo, campania_historica=campania
            )

        data = build_pyomo_input_data()

        self.assertEqual(data["ch"], ["CH1", "CH2", "CH3"])
        self.assertEqual(data["xh_dict"][("TRIGO", "J1", "CH1")], 1)
        self.assertEqual(data["xh_dict"][("TRIGO", "J1", "CH2")], 1)
        self.assertEqual(data["xh_dict"][("TRIGO", "J1", "CH3")], 1)

    def test_old_campaign_is_stored_but_excluded_from_solver_input(self):
        lote, cultivo = self._crear_lote_cultivo()
        vieja = CampaniaHistorica.objects.create(
            codigo="CH2015", anio_inicio=2015
        )
        HistorialLoteCultivo.objects.create(
            lote=lote, cultivo=cultivo, campania_historica=vieja
        )

        data = build_pyomo_input_data()

        # Stored for display…
        self.assertTrue(
            HistorialLoteCultivo.objects.filter(
                lote=lote, campania_historica=vieja
            ).exists()
        )
        # …but excluded from the model window (older than 3 campaigns)
        self.assertEqual(data["ch"], ["CH1", "CH2", "CH3"])
        self.assertFalse(
            any(key[1] == "J1" for key in data["xh_dict"].keys())
        )

    def test_absent_record_maps_to_zero_but_present_record_maps_to_one(self):
        lote, cultivo = self._crear_lote_cultivo()
        campania = CampaniaHistorica.objects.create(
            codigo="CH2023", anio_inicio=2023
        )
        HistorialLoteCultivo.objects.create(
            lote=lote, cultivo=cultivo,
            campania_historica=campania, presente=False,
        )

        data = build_pyomo_input_data()

        self.assertEqual(data["xh_dict"][("TRIGO", "J1", "CH2")], 0)


class CargarInputHistorialMappingTest(TestCase):
    def test_input_v1_imports_soil_names_and_configured_costs(self):
        input_path = settings.BASE_DIR / "docs" / "Input v1.xlsx"

        CargarInputCommand().handle(archivo=str(input_path))

        self.assertEqual(TipoSuelo.objects.get(codigo="S1").nombre, "Molisol")
        self.assertEqual(TipoSuelo.objects.get(codigo="S2").nombre, "Alfisol")
        self.assertEqual(TipoSuelo.objects.get(codigo="S3").nombre, "Vertisol")
        self.assertTrue(Costo.objects.exists())
        self.assertFalse(Costo.objects.filter(configurado=False).exists())

    @patch("core.management.commands.cargar_input.pd.read_excel")
    def test_tipo_suelo_uses_business_names(self, read_excel):
        import pandas as pd

        sets = pd.DataFrame([[None] * 6 for _ in range(3)])
        sets.iloc[:, 5] = ["S1", "S2", "S3"]
        read_excel.return_value = sets

        CargarInputCommand()._cargar_tipos_suelo(object())

        self.assertEqual(TipoSuelo.objects.get(codigo="S1").nombre, "Molisol")
        self.assertEqual(TipoSuelo.objects.get(codigo="S2").nombre, "Alfisol")
        self.assertEqual(TipoSuelo.objects.get(codigo="S3").nombre, "Vertisol")

    def test_ch_columns_map_to_years_before_current_campaign(self):
        # No Campania rows -> base falls back to ANIO_INICIO_CAMPANIA_ACTUAL (2025)
        ch1, created = campania_historica_desde_columna_excel("CH1")
        self.assertTrue(created)
        self.assertEqual(ch1.anio_inicio, 2024)
        self.assertEqual(ch1.codigo, "CH1")

        ch3, _ = campania_historica_desde_columna_excel("CH3")
        self.assertEqual(ch3.anio_inicio, 2022)
        self.assertEqual(ch3.codigo, "CH3")

    def test_mapping_is_idempotent_with_backfilled_rows(self):
        ch1, created = campania_historica_desde_columna_excel("CH1")
        self.assertTrue(created)

        again, created = campania_historica_desde_columna_excel("CH1")
        self.assertFalse(created)
        self.assertEqual(ch1.pk, again.pk)
        self.assertEqual(CampaniaHistorica.objects.count(), 1)

    def test_mapping_uses_c1_fecha_inicio_when_available(self):
        Campania.objects.create(
            codigo="C1", orden=1, fecha_inicio=date(2026, 7, 1)
        )
        ch1, _ = campania_historica_desde_columna_excel("CH1")
        self.assertEqual(ch1.anio_inicio, 2025)

    def test_mapping_reuses_existing_row_for_the_same_year(self):
        # A producer-loaded campaign for the same year must be reused,
        # keeping HistorialLoteCultivo references consistent.
        existente = CampaniaHistorica.objects.create(
            codigo="CH2024", anio_inicio=2024
        )
        ch1, created = campania_historica_desde_columna_excel("CH1")
        self.assertFalse(created)
        self.assertEqual(ch1.pk, existente.pk)


class DeployReleaseCommandTest(TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("core.management.commands.deploy_release.call_command")
    def test_release_migrates_and_loads_input_v1(self, call_command_mock):
        DeployReleaseCommand().handle()

        self.assertEqual(call_command_mock.call_args_list[0].args, ("migrate",))
        self.assertEqual(
            call_command_mock.call_args_list[0].kwargs,
            {"interactive": False},
        )
        self.assertEqual(
            call_command_mock.call_args_list[1].args[0],
            "cargar_input",
        )
        self.assertTrue(
            call_command_mock.call_args_list[1].args[1]
            .replace("\\", "/")
            .endswith("docs/Input v1.xlsx")
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
