from core.models import Campania, Costo, TipoCosto
from core.services.costos import consultar_costos
from .service_support import ServiceTestCase


class CostoQueryTest(ServiceTestCase):
    def test_general_and_rental_pagination_are_independent(self):
        renta = TipoCosto.objects.create(codigo="frc", descripcion="Arrendamiento")
        for index in range(2, 10):
            campania = Campania.objects.create(codigo=f"C{index}", orden=index)
            Costo.objects.create(cultivo=self.cultivo, campania=campania, tipo_costo=self.tipo, valor=index)
            Costo.objects.create(cultivo=self.cultivo, campania=campania, tipo_costo=renta, lote=self.lote, valor=index)
        data = consultar_costos(selected_page="2", selected_arrendamiento_page="1")
        self.assertEqual([c.valor for c in data["page_obj"]], [8, 9])
        self.assertEqual([c.valor for c in data["arrendamiento_page_obj"]], list(range(2, 9)))
        self.assertEqual(data["paginator"].count, 9)
        self.assertEqual(data["arrendamiento_paginator"].count, 8)
        filtered = consultar_costos(selected_campania=str(self.campania.pk), selected_cultivo=str(self.cultivo.pk))
        self.assertEqual(list(filtered["page_obj"]), [self.costo])
        self.assertEqual(list(filtered["arrendamiento_page_obj"]), [])
