from unittest.mock import patch

from django.core.exceptions import ValidationError

from core.models import Costo, TipoCosto
from core.services.costos import actualizar_costos
from .service_support import ServiceTestCase


class CostoServiceTest(ServiceTestCase):
    def otro_costo(self):
        tipo = TipoCosto.objects.create(codigo="hc", descripcion="Cosecha")
        return Costo.objects.create(
            cultivo=self.cultivo, tipo_costo=tipo, campania=self.campania,
            valor=50, configurado=False,
        )

    def test_invalid_value_prevents_all_updates(self):
        otro = self.otro_costo()
        for invalid in ("texto", "-1", ""):
            with self.subTest(value=invalid), self.assertRaises(ValidationError):
                actualizar_costos(self.editor, {self.costo.pk: "200", otro.pk: invalid})
            self.costo.refresh_from_db()
            self.assertEqual(self.costo.valor, 100)
            self.assertFalse(self.costo.configurado)

    def test_saves_valid_values_while_enable_remains_pending(self):
        self.otro_costo()
        result = actualizar_costos(self.editor, {self.costo.pk: 200}, cultivo_id=self.cultivo.pk, habilitar=True)
        self.assertEqual(result.modificados, 1)
        self.assertEqual(result.pendientes, 1)
        self.assertIsNone(result.cultivo_habilitado)
        self.costo.refresh_from_db()
        self.cultivo.refresh_from_db()
        self.assertEqual(self.costo.valor, 200)
        self.assertTrue(self.costo.configurado)
        self.assertFalse(self.cultivo.habilitado_optimizacion)

    def test_unchanged_value_counts_as_reviewed_and_enables_crop(self):
        result = actualizar_costos(self.editor, {self.costo.pk: 100}, cultivo_id=self.cultivo.pk, habilitar=True)
        self.assertEqual(result.modificados, 0)
        self.assertEqual(result.pendientes, 0)
        self.assertEqual(result.cultivo_habilitado.pk, self.cultivo.pk)
        self.costo.refresh_from_db()
        self.cultivo.refresh_from_db()
        self.assertTrue(self.costo.configurado)
        self.assertTrue(self.cultivo.habilitado_optimizacion)

    def test_missing_cost_is_ignored(self):
        result = actualizar_costos(self.editor, {self.costo.pk + 1000: 200})
        self.assertEqual(result.modificados, 0)
        self.assertEqual(Costo.objects.count(), 1)

    def test_failure_enabling_crop_rolls_back_cost_changes(self):
        with patch("core.services.costos.Cultivo.save", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                actualizar_costos(self.editor, {self.costo.pk: 200}, cultivo_id=self.cultivo.pk, habilitar=True)
        self.costo.refresh_from_db()
        self.assertEqual(self.costo.valor, 100)
        self.assertFalse(self.costo.configurado)
