from unittest.mock import patch

from core.models import Ambiente, Lote
from core.services import lotes
from .service_support import ServiceTestCase


class LoteServiceTest(ServiceTestCase):
    def test_create_rolls_back_lote_when_ambiente_persistence_fails(self):
        with patch("core.services.lotes.Ambiente.objects.bulk_create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                lotes.crear_lote(self.editor, nombre="Nuevo", ambientes=[(self.suelo.pk, "A", 20)])
        self.assertEqual(Lote.objects.count(), 1)
        self.assertEqual(Ambiente.objects.count(), 1)

    def test_update_restores_lote_and_original_ambientes_on_failure(self):
        before = list(Ambiente.objects.values())
        with patch("core.services.lotes.Ambiente.objects.bulk_create", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                lotes.actualizar_lote(
                    self.editor, self.lote.pk, nombre="Modificado", habilitado=False,
                    ambientes=[(self.suelo.pk, "A", 20)],
                )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.nombre, "Lote 1")
        self.assertEqual(self.lote.superficie_ha, 10)
        self.assertTrue(self.lote.habilitado)
        self.assertEqual(list(Ambiente.objects.values()), before)
