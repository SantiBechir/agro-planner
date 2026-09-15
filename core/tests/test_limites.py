from django.test import TestCase
from django.core.exceptions import ValidationError
from core.models import Cultivo, Campania, LimiteSuperficieCultivoCampania


class LimiteSuperficieCultivoCampaniaTest(TestCase):
    def setUp(self):
        self.cultivo = Cultivo.objects.create(
            codigo="TRIGO_LIMITE",
            nombre="Trigo límite",
            tipo=Cultivo.Tipo.PRINCIPAL,
            duracion_dias=120,
            siembra_inicio=1,
            siembra_fin=60,
        )
        self.campania = Campania.objects.create(codigo="C1", orden=1)

    def test_rejects_negative_or_inverted_limits(self):
        with self.assertRaises(ValidationError):
            LimiteSuperficieCultivoCampania(
                cultivo=self.cultivo,
                campania=self.campania,
                min_ha=-1,
                max_ha=10,
            ).full_clean()
        with self.assertRaises(ValidationError):
            LimiteSuperficieCultivoCampania(
                cultivo=self.cultivo,
                campania=self.campania,
                min_ha=11,
                max_ha=10,
            ).full_clean()
