from django.test import TestCase
from core.models import Cultivo, TipoSuelo, Lote, TipoCosto, Costo, Campania, CampaniaHistorica, HistorialLoteCultivo, LimiteSuperficieCultivoCampania
from core.services.optimization_inputs import build_pyomo_input_data
from core.services.costos import COMPONENTES_SIEMBRA


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

    def test_derives_sowing_cost_and_exposes_surface_limits(self):
        _, cultivo = self._crear_lote_cultivo()
        campania = Campania.objects.create(codigo="C1", orden=1)
        for index, code in enumerate(COMPONENTES_SIEMBRA, start=1):
            cost_type = TipoCosto.objects.create(
                codigo=code, descripcion=code, unidad="USD/ha"
            )
            Costo.objects.create(
                cultivo=cultivo,
                tipo_costo=cost_type,
                campania=campania,
                valor=index * 10,
            )
        LimiteSuperficieCultivoCampania.objects.create(
            cultivo=cultivo, campania=campania, min_ha=15, max_ha=120
        )

        data = build_pyomo_input_data()

        self.assertEqual(data["sc_dict"][("TRIGO", "C1")], 150)
        self.assertEqual(data["minha_dict"][("TRIGO", "C1")], 15)
        self.assertEqual(data["maxha_dict"][("TRIGO", "C1")], 120)
