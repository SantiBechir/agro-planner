from unittest.mock import patch

from core.models import CampaniaHistorica, HistorialLoteCultivo
from core.services.historial import cargar_historial
from .service_support import ServiceTestCase


class HistorialServiceTest(ServiceTestCase):
    def test_failed_replacement_restores_original_history(self):
        cargar_historial(self.editor, self.lote.pk, anio_inicio=2024,
                         cultivo_1_id=self.cultivo.pk, rendimiento_1="3500")
        before = list(HistorialLoteCultivo.objects.values())
        with patch("core.services.historial.HistorialLoteCultivo.objects.bulk_create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                cargar_historial(self.editor, self.lote.pk, anio_inicio=2024,
                                 cultivo_1_id=self.cultivo.pk, rendimiento_1="4000")
        self.assertEqual(list(HistorialLoteCultivo.objects.values()), before)

    def test_failed_creation_does_not_leave_historical_campaign(self):
        with patch("core.services.historial.HistorialLoteCultivo.objects.bulk_create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                cargar_historial(self.editor, self.lote.pk, anio_inicio=2024, cultivo_1_id=self.cultivo.pk)
        self.assertFalse(CampaniaHistorica.objects.exists())
        self.assertFalse(HistorialLoteCultivo.objects.exists())
