import json

from django.http import QueryDict
from django.test import SimpleTestCase

from core.presentation import economia
from core.views.costos import _filtros_costos


class EconomicPresentationTest(SimpleTestCase):
    def margin_row(self, **changes):
        row = {
            "cultivo": "TRIGO", "cultivo_id": 1, "campania": "2025/2026", "campania_id": 1,
            "suelo": "Molisol", "suelo_id": 1, "nivel": "M", "rendimiento": 4,
            "precio_cosecha": 250, "ingreso_bruto": 1000, "costo_cultivo": 100,
            "costo_cosecha": 20, "costo_comercializacion": 10, "costo_acondicionamiento": 5,
            "costo_flete": 15, "costo_arrendamiento": 50, "subtotal_costos": 150,
            "costos_directos": 150, "margen_bruto": 850, "margen_con_arrendamiento": 800,
            "rendimiento_indiferencia": 0.5,
        }
        return {**row, **changes}

    def break_even_row(self, **changes):
        return {
            "cultivo": "TRIGO", "cultivo_id": 1, "campania": "2025/2026", "campania_id": 1,
            "suelo": "Molisol", "suelo_id": 1, "nivel": "M", "precio_neto": 240,
            "rendimiento_estimado": 4, "rendimiento_indiferencia": 0.5, **changes,
        }

    def test_filter_adapter_preserves_multivalues_and_defaults(self):
        filters = _filtros_costos(QueryDict(
            "mb_campania=2&mb_campania=1&ri_cultivo=4&ri_cultivo=8&"
            "tab=unknown&mb_view=unknown&ri_view=lista&mb_cultivo_mode=unknown&page=2"
        ))
        self.assertEqual(filters["mb_selected_campanias"], ["2", "1"])
        self.assertEqual(filters["ri_selected_cultivos"], ["4", "8"])
        self.assertEqual(filters["selected_tab"], "detalle")
        self.assertEqual(filters["mb_view"], "grafico")
        self.assertEqual(filters["ri_view"], "lista")
        self.assertEqual(filters["mb_cultivo_mode"], "selected")
        self.assertEqual(filters["selected_page"], "2")
        self.assertEqual(filters["selected_arrendamiento_page"], "1")

    def test_standard_filters_apply_to_both_indicators_without_mutating_input(self):
        rows = [self.margin_row(), self.margin_row(campania_id=2), self.margin_row(suelo_id=2)]
        data = {"margins": rows, "break_even": list(rows)}
        filtered = economia.filtrar_indicadores(
            data, selected_campania="1", selected_suelo="1", selected_cultivo="1",
        )
        self.assertEqual(filtered, {"margins": [rows[0]], "break_even": [rows[0]]})
        self.assertEqual(len(data["margins"]), 3)

    def test_margin_graph_uses_medium_values_and_keeps_missing_levels(self):
        rows = [self.margin_row(nivel="A", costo_cultivo=120), self.margin_row()]
        graphs = economia.preparar_graficos_margen(
            rows, mb_selected_campanias=["1"], mb_selected_suelos=["1"],
            mb_selected_cultivos=["1"], mb_cultivo_mode="selected",
        )
        self.assertEqual(len(graphs), 1)
        data = json.loads(graphs[0]["chart_data"])
        self.assertEqual(data["datasets"][0]["data"], [100, 20, 10, 5, 15, 50])
        detail = next(row for row in graphs[0]["detalle"] if row["label"] == "Costo de cultivo (USD/ha)")
        self.assertEqual((detail["alto"], detail["medio"], detail["bajo"]), (120, 100, None))
        fallback = economia.preparar_graficos_margen(
            rows[:1], mb_selected_campanias=[], mb_selected_suelos=[],
            mb_selected_cultivos=[], mb_cultivo_mode="all",
        )
        self.assertEqual(json.loads(fallback[0]["chart_data"])["datasets"][0]["data"][0], 120)

    def test_empty_selection_differs_from_all_crops(self):
        args = dict(mb_selected_campanias=[], mb_selected_suelos=[], mb_selected_cultivos=[])
        self.assertEqual(economia.preparar_graficos_margen([self.margin_row()], mb_cultivo_mode="selected", **args), [])
        self.assertEqual(len(economia.preparar_graficos_margen([self.margin_row()], mb_cultivo_mode="all", **args)), 1)
        result = economia.preparar_grafico_indiferencia(
            {"break_even": [self.break_even_row()]}, ri_selected_campanias=[],
            ri_selected_suelos=[], ri_selected_cultivos=[], ri_cultivo_mode="selected",
        )
        self.assertFalse(result["ri_chart_has_data"])
        self.assertEqual(json.loads(result["ri_chart_data"]), {"labels": [], "datasets": []})
        self.assertIsNone(result["ri_maximo_kg"])

    def test_break_even_graph_units_missing_values_and_campaign_colors(self):
        rows = [
            self.break_even_row(),
            self.break_even_row(cultivo="SOJA", cultivo_id=2, rendimiento_indiferencia=0.7),
            self.break_even_row(campania_id=2, campania="2026/2027", rendimiento_indiferencia=0.8),
            self.break_even_row(nivel="A", rendimiento_indiferencia=999),
            self.break_even_row(cultivo="SIN_PRECIO", cultivo_id=3, rendimiento_indiferencia=None),
        ]
        result = economia.preparar_grafico_indiferencia(
            {"break_even": rows}, ri_selected_campanias=[], ri_selected_suelos=[],
            ri_selected_cultivos=[], ri_cultivo_mode="all",
        )
        data = json.loads(result["ri_chart_data"])
        self.assertEqual(data["labels"], ["SOJA", "TRIGO"])
        self.assertEqual([d["data"] for d in data["datasets"]], [[700, 500], [None, 800]])
        self.assertEqual(data["datasets"][0]["backgroundColor"], "#4d8b4f")
        self.assertEqual(data["datasets"][1]["backgroundColor"], "#74a576")
        self.assertEqual(result["ri_maximo_kg"], 800)
        self.assertEqual(result["ri_chart_campaign_count"], 2)
        self.assertEqual(result["ri_chart_soil_count"], 1)

    def test_tables_preserve_missing_levels_and_break_even(self):
        data = economia.preparar_tablas({"margins": [self.margin_row()], "break_even": [self.break_even_row()]})
        self.assertEqual(data["margenes"][0]["margen_con_arrendamiento"], 800)
        grouped = data["indiferencias_agrupadas"][0]
        self.assertEqual(grouped["rendimiento_medio"], 4)
        self.assertIsNone(grouped["rendimiento_alto"])
        self.assertIsNone(grouped["rendimiento_bajo"])
        self.assertEqual(grouped["rendimiento_indiferencia"], 0.5)
