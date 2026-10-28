"""Orden visible de lotes, incluyendo J10 y la paginación de arrendamientos."""
from copy import deepcopy

from django.urls import reverse

from core.models import AsignacionLoteSlot, Costo, Lote, Planificacion, SlotSiembra, TipoCosto
from core.services.costos import consultar_costos
from core.services.optimization_inputs import build_pyomo_input_data
from core.services.planificacion_escenario import congelar_entradas
from core.views.planificaciones import _build_gantt_data
from .service_support import ServiceTestCase


class OrdenLotesTest(ServiceTestCase):
    def setUp(self):
        # Insertion order deliberately differs from both alphabetical and numeric order.
        for numero in [10, 3, 8, 2, 9, 4, 7, 5, 6]:
            Lote.objects.create(
                usuario=self.editor, codigo=f"J{numero}", nombre=f"Lote {numero}",
                superficie_ha=10, tipo_suelo=self.suelo,
                max_cultivos_principales=10, max_cultivos_secundarios=10,
            )
        self.esperado = [f"J{numero}" for numero in range(1, 11)]
        self.slot = SlotSiembra.objects.create(codigo="T1", orden=1, campania=self.campania)
        self.client.force_login(self.editor)

    def test_catalog_configuration_and_new_snapshots_use_numeric_order(self):
        for ruta in ["lote_list", "planificacion_configuracion"]:
            response = self.client.get(reverse(ruta))
            self.assertEqual([lote.codigo for lote in response.context["lotes"]], self.esperado)
        entradas = build_pyomo_input_data(self.editor)
        self.assertEqual(entradas["j"], self.esperado)
        snapshot = congelar_entradas(entradas, self.editor)
        self.assertEqual([lote["codigo"] for lote in snapshot["etiquetas"]["lotes"]], self.esperado)

    def test_existing_snapshot_is_displayed_in_numeric_order_without_rewriting_it(self):
        snapshot = congelar_entradas(build_pyomo_input_data(self.editor), self.editor)
        snapshot["etiquetas"]["lotes"].sort(key=lambda lote: lote["codigo"])
        original = deepcopy(snapshot)
        plan = Planificacion.objects.create(usuario=self.editor, nombre="Orden histórico", datos_entrada=snapshot)
        response = self.client.get(reverse("planificacion_datos", args=[plan.pk]))
        self.assertEqual([lote["codigo"] for lote in response.context["datos"]["lotes"]], self.esperado)
        plan.refresh_from_db()
        self.assertEqual(plan.datos_entrada, original)

    def test_disabling_a_lot_does_not_move_it_after_j10_in_catalog(self):
        Lote.objects.filter(usuario=self.editor, codigo="J2").update(habilitado=False)
        response = self.client.get(reverse("lote_list"))
        self.assertEqual([lote.codigo for lote in response.context["lotes"]], self.esperado)

    def test_gantt_and_assignment_rows_use_numeric_order_and_slot_order(self):
        plan = Planificacion.objects.create(usuario=self.editor, nombre="Gantt")
        otro_slot = SlotSiembra.objects.create(codigo="T2", orden=2, campania=self.campania)
        for lote in Lote.objects.filter(usuario=self.editor):
            for slot in [otro_slot, self.slot]:
                AsignacionLoteSlot.objects.create(
                    planificacion=plan, lote=lote, cultivo=self.cultivo, slot=slot,
                    dia_siembra=1, dia_cosecha=120,
                )
        filas, lotes = _build_gantt_data(plan.asignaciones.select_related("lote", "cultivo", "slot").order_by("lote__codigo", "-slot__orden"))
        self.assertEqual(lotes, self.esperado)
        self.assertEqual([(fila["lote"], fila["slot"]) for fila in filas],
                         [(codigo, slot) for codigo in self.esperado for slot in ["T1", "T2"]])
        self.assertEqual(filas[-1]["y_pos"], 9)

    def test_rental_costs_are_sorted_before_pagination(self):
        renta = TipoCosto.objects.create(codigo="frc", descripcion="Arrendamiento")
        for lote in Lote.objects.filter(usuario=self.editor):
            Costo.objects.create(usuario=self.editor, cultivo=self.cultivo, campania=self.campania,
                                 tipo_costo=renta, lote=lote, valor=10)
        codigos = []
        for pagina in ["1", "2"]:
            datos = consultar_costos(self.editor, selected_tipo=str(renta.pk), selected_arrendamiento_page=pagina)
            codigos.extend(costo.lote.codigo for costo in datos["arrendamiento_page_obj"])
        self.assertEqual(codigos, self.esperado)
