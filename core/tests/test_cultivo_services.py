from unittest.mock import patch

from django.core.exceptions import ValidationError

from core.models import CompatibilidadCultivoSuelo, Costo, Cultivo, RendimientoCultivoSuelo
from core.services.cultivos import crear_cultivo
from .service_support import ServiceTestCase


class CultivoServiceTest(ServiceTestCase):
    def test_failed_cost_creation_rolls_back_all_agronomic_data(self):
        with patch("core.services.cultivos.Costo.objects.bulk_create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                crear_cultivo(self.editor, **self.datos_cultivo())
        self.assertEqual(Cultivo.objects.count(), 1)
        self.assertEqual(Costo.objects.count(), 1)
        self.assertFalse(RendimientoCultivoSuelo.objects.exists())
        self.assertFalse(CompatibilidadCultivoSuelo.objects.exists())

    def test_invalid_yield_raises_validation_error_without_partial_crop(self):
        datos = self.datos_cultivo()
        datos["rendimientos"] = {self.suelo.pk: "inválido"}
        with self.assertRaises(ValidationError):
            crear_cultivo(self.editor, **datos)
        self.assertEqual(Cultivo.objects.count(), 1)
        self.assertFalse(RendimientoCultivoSuelo.objects.exists())

    def test_creates_pending_crop_and_economic_configuration(self):
        cultivo = crear_cultivo(self.editor, **self.datos_cultivo())
        self.assertFalse(cultivo.habilitado_optimizacion)
        costo = cultivo.costo_set.get()
        self.assertEqual(costo.campania_id, self.campania.pk)
        self.assertFalse(costo.configurado)
        self.assertEqual(RendimientoCultivoSuelo.objects.get(cultivo=cultivo).valor, 3000)
        self.assertTrue(CompatibilidadCultivoSuelo.objects.get(cultivo=cultivo).compatible)
