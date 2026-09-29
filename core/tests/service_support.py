"""Datos comunes para probar las entradas de servicios sin una petición HTTP."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.roles import EDITOR_ROLE, READER_ROLE, set_functional_role
from core.models import Ambiente, Campania, Costo, Cultivo, Lote, TipoCosto, TipoSuelo


class ServiceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.editor = user_model.objects.create_user(
            email="editor@services.test", first_name="Editor", last_name="Test",
        )
        cls.reader = user_model.objects.create_user(
            email="reader@services.test", first_name="Reader", last_name="Test",
        )
        set_functional_role(cls.editor, EDITOR_ROLE)
        set_functional_role(cls.reader, READER_ROLE)
        cls.suelo = TipoSuelo.objects.create(codigo="S1", nombre="Molisol")
        cls.campania = Campania.objects.create(
            codigo="C1", orden=1, fecha_inicio=date(2025, 6, 1),
        )
        cls.cultivo = Cultivo.objects.create(
            codigo="TRIGO", nombre="Trigo", duracion_dias=120,
            siembra_inicio=1, siembra_fin=60, habilitado_optimizacion=False,
        )
        cls.lote = Lote.objects.create(
            codigo="J1", nombre="Lote 1", superficie_ha=10, tipo_suelo=cls.suelo,
            max_cultivos_principales=10, max_cultivos_secundarios=10,
        )
        cls.ambiente = Ambiente.objects.create(
            lote=cls.lote, tipo_suelo=cls.suelo, superficie_ha=10, rendimiento_esperado="M",
        )
        cls.tipo = TipoCosto.objects.create(codigo="fsp", descripcion="Precio")
        cls.costo = Costo.objects.create(
            cultivo=cls.cultivo, tipo_costo=cls.tipo, campania=cls.campania,
            valor=100, configurado=False,
        )

    def datos_cultivo(self):
        return {
            "nombre": "Soja", "tipo": Cultivo.Tipo.PRINCIPAL, "duracion_dias": "120",
            "siembra_inicio_fecha": "2025-06-01", "siembra_fin_fecha": "2025-07-01",
            "no_repetir": False, "rendimientos": {self.suelo.pk: "3000"},
        }
