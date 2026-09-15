from django.test import TestCase
from core.models import Campania, CampaniaHistorica
from datetime import date


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
