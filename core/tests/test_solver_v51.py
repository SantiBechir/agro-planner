from unittest.mock import patch

import pyomo.environ as pyo
from django.test import SimpleTestCase, TestCase

from core.models import (
    Ambiente, Campania, CompatibilidadCultivoSuelo, Costo, Cultivo, Lote,
    Planificacion, SlotSiembra, TipoCosto, TipoSuelo,
)
from core.services.economic_indicators import build_economic_indicators
from core.services.optimization_inputs import build_pyomo_input_data
from core.services.solver import build_optimization_model, run_optimization


def example_data():
    """100 ha, dos ambientes y dos cultivos obligados por sus slots."""
    crops = ['MAIN', 'SECOND']
    data = {
        'j': ['J1'], 'i': crops, 'i_p': ['MAIN'], 'i_s': ['SECOND'],
        'i_ns': [], 's': ['S1', 'S2'], 'c': ['C1'], 't': ['T1', 'T2'],
        'ch': ['CH1'], 'l': ['L0', 'L1'], 'ha': {'J1': 100},
        'max_m': {'J1': 1}, 'max_s': {'J1': 1}, 'sueloj': {'J1': 'S1'},
        'tc_dict': {'C1': ['T1', 'T2']}, 'ord_dict': {'C1': 1},
        'lag_dict': {'L0': 0, 'L1': 1}, 'alfa_dict': {'L0': 1, 'L1': .5},
        'ep_dict': {('J1', 'S1'): .6, ('J1', 'S2'): .4},
        'py_dict': {('J1', 'S1'): 1.2, ('J1', 'S2'): .8},
        'gt': dict.fromkeys(crops, 80), 'st_start': dict.fromkeys(crops, 0),
        'st_end': dict.fromkeys(crops, 300),
        'setup_dict': {(a, b): 10 for a in crops for b in crops},
        'ar_dict': {}, 'sueloi_dict': {}, 'xh_dict': {},
        'red_dict': {('SECOND', 'MAIN'): .2},
        'y_max_dict': {(s, i): y for s, y in [('S1', 4), ('S2', 2)] for i in crops},
        'minha_dict': {('MAIN', 'C1'): 100},
        'maxha_dict': {(i, 'C1'): 100 for i in crops},
    }
    for code, value in [('fsp', 200), ('sc', 50), ('hc', 20), ('cp', 10), ('cst', 30), ('clt', 40)]:
        data[code + '_dict'] = {(i, 'C1'): value for i in crops}
    for code, value in [('tf', .05), ('scp', .5), ('st', .25)]:
        data[code + '_dict'] = dict.fromkeys(crops, value)
    for code, value in [('frc', 100), ('vr', .1)]:
        data[code + '_dict'] = {(i, 'J1', 'C1'): value for i in crops}
    return data


class SolverV51Test(SimpleTestCase):
    def test_solves_weighted_yield_rotations_slots_and_costs(self):
        model = build_optimization_model(example_data())
        result = pyo.SolverFactory('highs').solve(model)
        self.assertEqual(result.solver.termination_condition, pyo.TerminationCondition.optimal)
        self.assertTrue(model.X['MAIN', 'J1', 'T1'].fixed)
        self.assertTrue(model.X['SECOND', 'J1', 'T2'].fixed)
        # 100 * (.6 * 1.2 * 4 + .4 * .8 * 2) = 352 t base.
        self.assertAlmostEqual(pyo.value(model.Y['SECOND', 'J1', 'T1']), 352)
        self.assertAlmostEqual(pyo.value(model.Y['MAIN', 'J1', 'T2']), 422.4)
        self.assertGreaterEqual(pyo.value(model.ST['J1', 'T2'] - model.ST['J1', 'T1']), 90)
        self.assertAlmostEqual(pyo.value(model.RCOSTS), 20000 + 20 * 774.4)
        self.assertAlmostEqual(pyo.value(model.PHCOSTS), (10 + 5 + 7.5 + 40) * 774.4)
        self.assertAlmostEqual(pyo.value(model.PROFIT), 200 * 774.4 - 14000 - 20000 - 82.5 * 774.4)

    def test_surface_limit_can_make_plan_infeasible(self):
        data = example_data()
        data['maxha_dict'][('MAIN', 'C1')] = 99
        model = build_optimization_model(data)
        result = pyo.SolverFactory('highs').solve(model, load_solutions=False)
        self.assertEqual(result.solver.termination_condition, pyo.TerminationCondition.infeasible)

    def test_compatibility_uses_half_of_plot_area(self):
        data = example_data()
        data['sueloi_dict'] = {('MAIN', 'S1'): 0, ('MAIN', 'S2'): 1}
        self.assertEqual(pyo.value(build_optimization_model(data).compat['MAIN', 'J1']), 0)
        data['ep_dict'] = {('J1', 'S1'): .5, ('J1', 'S2'): .5}
        self.assertEqual(pyo.value(build_optimization_model(data).compat['MAIN', 'J1']), 1)


class SolverV51PersistenceTest(TestCase):
    def test_environment_inputs_and_per_hectare_indicators(self):
        soils = [TipoSuelo.objects.create(codigo=code) for code in ['S1', 'S2']]
        lot = Lote.objects.create(codigo='J1', superficie_ha=100, tipo_suelo=soils[0],
                                 max_cultivos_principales=1, max_cultivos_secundarios=1)
        for soil, area, level in zip(soils, [60, 40], ['A', 'B']):
            Ambiente.objects.create(lote=lot, tipo_suelo=soil, superficie_ha=area,
                                    rendimiento_esperado=level)
        data = build_pyomo_input_data()
        self.assertEqual(data['ep_dict'], {('J1', 'S1'): .6, ('J1', 'S2'): .4})
        self.assertEqual(data['py_dict'], {('J1', 'S1'): 1.2, ('J1', 'S2'): .8})

        crop = Cultivo.objects.create(codigo='MAIN', duracion_dias=80, siembra_inicio=0, siembra_fin=300)
        campaign = Campania.objects.create(codigo='C1', orden=1)
        CompatibilidadCultivoSuelo.objects.create(cultivo=crop, tipo_suelo=soils[0], compatible=True)
        crop.rendimientocultivosuelo_set.create(tipo_suelo=soils[0], valor=4)
        for code, value in [('frc', 100), ('fsp', 200), ('st', .25), ('cst', 30), ('clt', 40)]:
            kind = TipoCosto.objects.create(codigo=code)
            Costo.objects.create(cultivo=crop, tipo_costo=kind, valor=value,
                                 campania=None if code == 'st' else campaign,
                                 lote=lot if code == 'frc' else None)
        indicators = build_economic_indicators()
        rows = indicators['margins']
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertAlmostEqual(row['costo_arrendamiento_fijo'], 100)
            self.assertAlmostEqual(row['costo_flete'], 47.5 * row['rendimiento'])

    def test_saved_assignments_reconcile_with_profit(self):
        data = example_data()
        soil = TipoSuelo.objects.create(codigo='S1')
        Lote.objects.create(codigo='J1', superficie_ha=100, tipo_suelo=soil,
                            max_cultivos_principales=1, max_cultivos_secundarios=1)
        for code in data['i']:
            Cultivo.objects.create(codigo=code, duracion_dias=80, siembra_inicio=0, siembra_fin=300)
        campaign = Campania.objects.create(codigo='C1', orden=1)
        for order, code in enumerate(data['t'], 1):
            SlotSiembra.objects.create(codigo=code, orden=order, campania=campaign)
        plan = Planificacion.objects.create(nombre='Modelo v5.1')
        with patch('core.services.solver.build_pyomo_input_data', return_value=data):
            self.assertTrue(run_optimization(plan.pk))
        plan.refresh_from_db()
        assignments = list(plan.asignaciones.all())
        self.assertEqual(len(assignments), 2)
        self.assertAlmostEqual(sum((a.ingreso - a.costo) * 100 for a in assignments), plan.profit)
        self.assertAlmostEqual(sum(a.rendimiento for a in assignments), 774.4)
        for assignment in assignments:
            self.assertAlmostEqual(assignment.dia_cosecha - assignment.dia_siembra, 80)
