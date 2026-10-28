"""Escenarios privados, entradas congeladas e integración con el solver real."""
import json
from copy import deepcopy
from datetime import date
from unittest.mock import patch

import pyomo.environ as pyo
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from core.models import (
    Campania, CampaniaHistorica, ConfiguracionCultivoUsuario, Costo, Cultivo,
    HistorialLoteCultivo, ImpactoRotacion, LimiteSuperficieCultivoCampania,
    Lote, NivelAntiguedad, Planificacion, RendimientoCultivoSuelo, SlotSiembra,
)
from core.services.planificaciones import solicitar_planificacion
from core.services.planificacion_escenario import congelar_entradas, restaurar_entradas
from core.services.solver import build_optimization_model, run_optimization
from core.views.planificaciones import _build_gantt_data
from .service_support import ServiceTestCase


class EscenarioPlanificacionTest(ServiceTestCase):
    def setUp(self):
        self.costo.configurado = True
        self.costo.save()
        self.barbecho = Cultivo.objects.create(
            codigo="BARBECHO", nombre="Barbecho", duracion_dias=0,
            siembra_inicio=0, siembra_fin=365,
        )
        self.campania2 = Campania.objects.create(codigo="C2", orden=2, fecha_inicio=date(2026, 6, 1))
        for n, campania in enumerate([self.campania, self.campania2]):
            for turno in range(2):
                SlotSiembra.objects.create(codigo=f"T{n * 2 + turno + 1}", orden=n * 2 + turno + 1, campania=campania)
        for n in range(1, 6):
            NivelAntiguedad.objects.create(codigo=f"L{n}", orden=n, lag=n - 1, alfa=.5)
        RendimientoCultivoSuelo.objects.create(cultivo=self.cultivo, tipo_suelo=self.suelo, valor=4)
        self.otro_lote = Lote.objects.create(
            usuario=self.editor, codigo="J2", nombre="Otro lote", superficie_ha=20,
            tipo_suelo=self.suelo, max_cultivos_principales=10, max_cultivos_secundarios=10,
        )
        self.otro_cultivo = Cultivo.objects.create(
            codigo="SOJA", nombre="Soja", duracion_dias=90, siembra_inicio=1, siembra_fin=200,
        )
        ConfiguracionCultivoUsuario.objects.create(usuario=self.editor, cultivo=self.otro_cultivo, habilitado_optimizacion=True)
        self.client.force_login(self.editor)

    def seleccion(self, cantidad=1, cultivo=None, lote=None):
        cultivo = cultivo or self.cultivo
        lote = lote or self.lote
        return {"cantidad_campanias": str(cantidad), "cultivos": [str(cultivo.pk)],
                "lotes": [str(lote.pk)], "limites": {
                    f"{cultivo.pk}_{campania.pk}": {"min": "0", "max": "10"}
                    for campania in [self.campania, self.campania2][:cantidad]}}

    def solicitar(self, **kwargs):
        return solicitar_planificacion(self.editor, nombre="Escenario privado", seleccion=self.seleccion(**kwargs))

    def post_data(self, seleccion=None):
        seleccion = seleccion or self.seleccion()
        data = {"nombre": "Desde el formulario", **{k: v for k, v in seleccion.items() if k != "limites"}}
        for key, limites in seleccion["limites"].items():
            data[f"min_{key}"], data[f"max_{key}"] = limites["min"], limites["max"]
        return data

    def test_get_configuration_and_history_do_not_create_limits(self):
        before = LimiteSuperficieCultivoCampania.objects.count()
        for url in ["planificacion_list", "planificacion_configuracion"]:
            self.assertEqual(self.client.get(reverse(url)).status_code, 200)
        self.assertEqual(LimiteSuperficieCultivoCampania.objects.count(), before)
        response = self.client.get(reverse("planificacion_configuracion"))
        state = json.loads(response.context["configuracion_json"])
        self.assertEqual(state["cantidad"], 2)
        self.assertEqual(len(state["cultivos"]), 2)
        self.assertEqual(len(state["lotes"]), 2)
        self.assertContains(response, 'value="500"')

    def test_selected_inputs_are_complete_and_round_trip_json(self):
        plan = self.solicitar()
        plan.refresh_from_db()
        data = restaurar_entradas(json.loads(json.dumps(plan.datos_entrada)))
        self.assertEqual(data["i"], [self.cultivo.codigo, "BARBECHO"])
        self.assertEqual(data["j"], [self.lote.codigo])
        self.assertEqual(data["c"], ["C1"])
        self.assertEqual(data["t"], ["T1", "T2"])
        self.assertEqual(data["maxha_dict"], {("TRIGO", "C1"): 10, ("BARBECHO", "C1"): 20})
        self.assertEqual(data["fsp_dict"], {("TRIGO", "C1"): 100})
        self.assertNotIn(self.otro_lote.codigo, data["ha"])
        self.assertEqual(congelar_entradas(data, self.editor), plan.datos_entrada)
        self.assertFalse(LimiteSuperficieCultivoCampania.objects.exists())

    def test_execution_limits_do_not_change_personal_defaults(self):
        limite = LimiteSuperficieCultivoCampania.objects.create(
            usuario=self.editor, cultivo=self.cultivo, campania=self.campania, min_ha=3, max_ha=7,
        )
        self.solicitar()
        limite.refresh_from_db()
        self.assertEqual((limite.min_ha, limite.max_ha), (3, 7))

    def test_rejects_invalid_selections_and_limits_without_job(self):
        cases = []
        for campo, valores in [("cantidad_campanias", ["0", "3", "1.5", "" ]),
                               ("cultivos", [[], ["999999"], [str(self.barbecho.pk)]]),
                               ("lotes", [[], ["999999"]])]:
            for valor in valores:
                seleccion = self.seleccion()
                seleccion[campo] = valor
                cases.append(seleccion)
        for limites in [{}, {"min": "nan", "max": "10"}, {"min": "0", "max": "inf"},
                        {"min": "-1", "max": "10"}, {"min": "10", "max": "5"}]:
            seleccion = self.seleccion()
            seleccion["limites"][f"{self.cultivo.pk}_{self.campania.pk}"] = limites
            cases.append(seleccion)
        for seleccion in cases:
            with self.subTest(seleccion=seleccion), self.assertRaises(ValidationError):
                solicitar_planificacion(self.editor, nombre="Inválida", seleccion=seleccion)
        self.assertFalse(Planificacion.objects.exists())

    def test_rejects_foreign_disabled_and_unavailable_items(self):
        self.lote.usuario = self.reader
        self.lote.save()
        with self.assertRaisesMessage(ValidationError, "lote propio"):
            self.solicitar()
        self.otro_lote.habilitado = False
        self.otro_lote.save()
        with self.assertRaisesMessage(ValidationError, "lote propio"):
            self.solicitar(lote=self.otro_lote)
        ConfiguracionCultivoUsuario.objects.filter(usuario=self.editor, cultivo=self.cultivo).update(habilitado_optimizacion=False)
        with self.assertRaisesMessage(ValidationError, "cultivo habilitado"):
            self.solicitar()

    def test_requires_barbecho_and_campaign_slots(self):
        self.barbecho.delete()
        with self.assertRaisesMessage(ValidationError, "Falta el barbecho"):
            self.solicitar()
        self.campania.slots.all().delete()
        with self.assertRaisesMessage(ValidationError, "turnos"):
            self.solicitar()

    def test_only_selected_costs_and_limits_are_validated(self):
        Costo.objects.create(usuario=self.editor, cultivo=self.cultivo, tipo_costo=self.tipo,
                             campania=self.campania2, valor=0, configurado=False)
        Costo.objects.create(usuario=self.editor, cultivo=self.otro_cultivo, tipo_costo=self.tipo,
                             campania=self.campania, valor=0, configurado=False)
        LimiteSuperficieCultivoCampania.objects.create(usuario=self.editor, cultivo=self.otro_cultivo,
                                                       campania=self.campania, min_ha=1000, max_ha=1000)
        self.solicitar()
        with self.assertRaisesMessage(ValidationError, "pendientes"):
            self.solicitar(cantidad=2)

    def test_minimum_uses_selected_surface_and_environment_compatibility(self):
        seleccion = self.seleccion()
        seleccion["limites"][f"{self.cultivo.pk}_{self.campania.pk}"] = {"min": "15", "max": "20"}
        with self.assertRaisesMessage(ValidationError, "superficie seleccionada"):
            solicitar_planificacion(self.editor, nombre="Exceso", seleccion=seleccion)

    def test_http_validation_preserves_form_and_explicit_selection_is_required(self):
        data = self.post_data()
        data["nombre"] = 'Nombre con "comillas"'
        data[f"min_{self.cultivo.pk}_{self.campania.pk}"] = "15.25"
        response = self.client.post(reverse("ejecutar_optimizacion"), data)
        self.assertContains(response, 'value="15.25"')
        self.assertEqual(response.context["nombre"], data["nombre"])
        state = json.loads(response.context["configuracion_json"])
        self.assertEqual(state["cultivos"], [str(self.cultivo.pk)])
        response = self.client.post(reverse("ejecutar_optimizacion"), {"nombre": "Sin selección"})
        self.assertContains(response, "Seleccioná campañas")
        self.assertFalse(Planificacion.objects.exists())

    def test_both_roles_can_set_execution_limits(self):
        for actor in [self.editor, self.reader]:
            self.lote.usuario = actor
            self.lote.save()
            self.client.force_login(actor)
            with self.subTest(actor=actor.email), patch("core.services.solver.run_optimization") as solver:
                response = self.client.post(reverse("ejecutar_optimizacion"), self.post_data())
                self.assertEqual(response.status_code, 302)
                plan = Planificacion.objects.get(usuario=actor)
                self.assertIsNotNone(plan.datos_entrada)
                solver.assert_not_called()

    def test_data_tab_is_private_read_only_and_available_in_all_states(self):
        plan = self.solicitar()
        url = reverse("planificacion_datos", args=[plan.pk])
        for estado in Planificacion.Estado.values:
            plan.estado = estado
            plan.save()
            response = self.client.get(url)
            self.assertContains(response, "Datos de ejecución")
            self.assertContains(response, "Lote 1")
            self.assertNotContains(response, '<input')
            self.assertNotContains(response, 'hx-trigger="every')
            result = self.client.get(reverse("planificacion_status", args=[plan.pk]))
            self.assertContains(result, url)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_configuration_and_execution_data_only_allow_get(self):
        plan = self.solicitar()
        for url in [reverse("planificacion_configuracion"), reverse("planificacion_datos", args=[plan.pk])]:
            self.assertEqual(self.client.post(url, {}).status_code, 405)

    def test_zero_surface_is_rejected_before_building_environment_proportions(self):
        Lote.objects.filter(pk=self.lote.pk).update(superficie_ha=0)
        with self.assertRaisesMessage(ValidationError, "superficie positiva"):
            self.solicitar()

    def test_legacy_missing_snapshot_is_not_reconstructed_by_get(self):
        plan = Planificacion.objects.create(usuario=self.editor, nombre="Antigua")
        self.assertContains(self.client.get(reverse("planificacion_datos", args=[plan.pk])), "Datos de ejecución no disponibles")
        plan.refresh_from_db()
        self.assertIsNone(plan.datos_entrada)

    @override_settings(MAX_ACTIVE_PLANIFICATIONS=1)
    def test_admission_limit_remains_enforced(self):
        self.solicitar()
        with self.assertRaisesMessage(ValidationError, "demasiadas"):
            self.solicitar()
        self.assertEqual(Planificacion.objects.count(), 1)

    def test_history_of_unselected_crop_still_affects_yield(self):
        historica = CampaniaHistorica.objects.create(codigo="CH2024", anio_inicio=2024)
        HistorialLoteCultivo.objects.create(lote=self.lote, cultivo=self.otro_cultivo, campania_historica=historica)
        ImpactoRotacion.objects.create(cultivo_previo=self.otro_cultivo, cultivo_actual=self.cultivo, valor=.4)
        data = restaurar_entradas(self.solicitar().datos_entrada)
        self.assertNotIn("SOJA", data["i"])
        self.assertIn("SOJA", data["i_hist"])
        model = build_optimization_model(data)
        self.assertEqual(pyo.value(model.xh["SOJA", "J1", "CH1"]), 1)
        self.assertAlmostEqual(pyo.value(model.history["TRIGO", "J1", "T1"].upper), 1.2)

    def test_real_solver_for_one_and_multiple_campaigns(self):
        for cantidad in [1, 2]:
            with self.subTest(cantidad=cantidad):
                plan = self.solicitar(cantidad=cantidad)
                self.assertTrue(run_optimization(plan.pk))
                plan.refresh_from_db()
                self.assertEqual(plan.estado, Planificacion.Estado.COMPLETADO)
                self.assertEqual(plan.asignaciones.count(), cantidad * 2)
                self.assertAlmostEqual(sum((a.ingreso - a.costo) * 10 for a in plan.asignaciones.all()), plan.profit)

    def test_queued_job_uses_snapshot_despite_catalog_changes(self):
        plan = self.solicitar()
        original = deepcopy(plan.datos_entrada)
        self.lote.superficie_ha = 50
        self.lote.habilitado = False
        self.lote.nombre = "Nuevo nombre"
        self.lote.codigo = "NUEVO"
        self.lote.save()
        self.costo.valor = 0
        self.costo.save()
        RendimientoCultivoSuelo.objects.update(valor=0)
        ConfiguracionCultivoUsuario.objects.update(habilitado_optimizacion=False)
        LimiteSuperficieCultivoCampania.objects.create(usuario=self.editor, cultivo=self.cultivo,
                                                       campania=self.campania, min_ha=999, max_ha=999)
        with patch("core.services.solver.build_pyomo_input_data", side_effect=AssertionError("No leer entradas actuales")):
            self.assertTrue(run_optimization(plan.pk))
        plan.refresh_from_db()
        self.assertEqual(plan.datos_entrada, original)
        self.assertGreater(plan.profit, 0)
        self.assertAlmostEqual(sum((a.ingreso - a.costo) * 10 for a in plan.asignaciones.all()), plan.profit)
        self.assertContains(self.client.get(reverse("planificacion_datos", args=[plan.pk])), "Lote 1")
        gantt, lotes = _build_gantt_data(plan.asignaciones.select_related("lote", "cultivo", "slot"), original)
        self.assertEqual(lotes, ["J1"])
        self.assertEqual(gantt[0]["fecha_siembra"], "01/06/2025")

    def test_legacy_worker_saves_snapshot_before_solving(self):
        data = restaurar_entradas(self.solicitar().datos_entrada)
        plan = Planificacion.objects.create(usuario=self.editor, nombre="Trabajo anterior")
        with patch("core.services.solver.build_pyomo_input_data", return_value=data) as construir:
            self.assertTrue(run_optimization(plan.pk))
            construir.assert_called_once_with(self.editor)
        plan.refresh_from_db()
        self.assertEqual(restaurar_entradas(plan.datos_entrada), data)
