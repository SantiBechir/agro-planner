from django.test import TestCase
from django.conf import settings
from django.core.management.base import CommandError
from io import StringIO
from unittest.mock import patch
from core.models import Ambiente, Cultivo, TipoSuelo, Lote, TipoCosto, Costo, Campania, CampaniaHistorica, LimiteSuperficieCultivoCampania
from core.management.commands.cargar_input import Command as CargarInputCommand, campania_historica_desde_columna_excel
from core.services.costos import COMPONENTES_SIEMBRA, calcular_costo_siembra
from core.services.input_v51 import InputValidationError, read_and_validate_input_v51
from datetime import date


class CargarInputHistorialMappingTest(TestCase):
    def test_input_v51_imports_the_complete_snapshot(self):
        input_path = settings.BASE_DIR / "docs" / "Input v5.1.xlsx"

        CargarInputCommand(stdout=StringIO()).handle(archivo=str(input_path))

        self.assertEqual(TipoSuelo.objects.get(codigo="S1").nombre, "Molisol")
        self.assertEqual(TipoSuelo.objects.get(codigo="S2").nombre, "Alfisol")
        self.assertEqual(TipoSuelo.objects.get(codigo="S3").nombre, "Vertisol")
        self.assertEqual(Lote.objects.filter(habilitado=True).count(), 10)
        self.assertEqual(Cultivo.objects.filter(habilitado_optimizacion=True).count(), 20)
        self.assertEqual(Campania.objects.count(), 3)
        self.assertEqual(LimiteSuperficieCultivoCampania.objects.count(), 60)
        self.assertEqual(TipoCosto.objects.count(), 15)
        self.assertFalse(Cultivo.objects.filter(codigo="VICIA").exists())
        self.assertTrue(Cultivo.objects.filter(codigo="VICIA CS").exists())
        self.assertFalse(TipoCosto.objects.filter(codigo="sc").exists())
        self.assertFalse(Costo.objects.filter(configurado=False).exists())

        for lote in Lote.objects.prefetch_related("ambientes"):
            self.assertAlmostEqual(
                sum(ambiente.superficie_ha for ambiente in lote.ambientes.all()),
                lote.superficie_ha,
            )
            self.assertTrue(
                all(
                    ambiente.rendimiento_esperado in {"A", "M", "B"}
                    for ambiente in lote.ambientes.all()
                )
            )

        cultivo = Cultivo.objects.get(codigo="COLZA")
        campania = Campania.objects.get(codigo="C1")
        components = {
            costo.tipo_costo.codigo: costo.valor
            for costo in Costo.objects.filter(
                cultivo=cultivo,
                campania=campania,
                tipo_costo__codigo__in=COMPONENTES_SIEMBRA,
            ).select_related("tipo_costo")
        }
        self.assertEqual(len(components), 5)
        self.assertAlmostEqual(calcular_costo_siembra(components), 442.65)

    def test_validate_only_does_not_write(self):
        input_path = settings.BASE_DIR / "docs" / "Input v5.1.xlsx"

        CargarInputCommand(stdout=StringIO()).handle(
            archivo=str(input_path), validar=True
        )

        self.assertEqual(Cultivo.objects.count(), 0)
        self.assertEqual(Costo.objects.count(), 0)

    def test_import_is_idempotent(self):
        input_path = settings.BASE_DIR / "docs" / "Input v5.1.xlsx"
        command = CargarInputCommand(stdout=StringIO())
        command.handle(archivo=str(input_path))
        first_counts = (
            Cultivo.objects.count(),
            Lote.objects.count(),
            Ambiente.objects.count(),
            Costo.objects.count(),
            LimiteSuperficieCultivoCampania.objects.count(),
        )

        command.handle(archivo=str(input_path))

        self.assertEqual(
            first_counts,
            (
                Cultivo.objects.count(),
                Lote.objects.count(),
                Ambiente.objects.count(),
                Costo.objects.count(),
                LimiteSuperficieCultivoCampania.objects.count(),
            ),
        )

    def test_import_disables_absent_entities_and_removes_legacy_sc(self):
        input_path = settings.BASE_DIR / "docs" / "Input v5.1.xlsx"
        stale_soil = TipoSuelo.objects.create(codigo="S_OLD", nombre="Viejo")
        stale_crop = Cultivo.objects.create(
            codigo="VICIA",
            nombre="Vicia anterior",
            tipo=Cultivo.Tipo.SECUNDARIO,
            duracion_dias=90,
            siembra_inicio=1,
            siembra_fin=30,
        )
        stale_lot = Lote.objects.create(
            codigo="J_OLD",
            nombre="Lote anterior",
            superficie_ha=20,
            max_cultivos_principales=1,
            max_cultivos_secundarios=1,
            tipo_suelo=stale_soil,
        )
        legacy_type = TipoCosto.objects.create(
            codigo="sc", descripcion="Costo agregado", unidad="USD/ha"
        )
        Costo.objects.create(
            cultivo=stale_crop, tipo_costo=legacy_type, valor=100
        )

        CargarInputCommand(stdout=StringIO()).handle(archivo=str(input_path))

        stale_crop.refresh_from_db()
        stale_lot.refresh_from_db()
        self.assertFalse(stale_crop.habilitado_optimizacion)
        self.assertFalse(stale_lot.habilitado)
        self.assertFalse(TipoCosto.objects.filter(codigo="sc").exists())

    @patch("core.management.commands.cargar_input.persist_input_v51")
    def test_import_rolls_back_if_persistence_fails(self, persist_mock):
        input_path = settings.BASE_DIR / "docs" / "Input v5.1.xlsx"

        def fail_after_write(data):
            TipoSuelo.objects.create(codigo="ROLLBACK", nombre="Temporal")
            raise RuntimeError("fallo simulado")

        persist_mock.side_effect = fail_after_write
        with self.assertRaises(CommandError):
            CargarInputCommand(stdout=StringIO()).handle(archivo=str(input_path))

        self.assertFalse(TipoSuelo.objects.filter(codigo="ROLLBACK").exists())

    def test_reader_rejects_missing_required_sheet(self):
        input_path = settings.BASE_DIR / "docs" / "Input v5.1.xlsx"
        fake_excel = type("FakeExcel", (), {"sheet_names": ["Sets"]})()
        with patch("core.services.input_v51.pd.ExcelFile", return_value=fake_excel):
            with self.assertRaisesRegex(InputValidationError, "Faltan hojas"):
                read_and_validate_input_v51(input_path)

    def test_ch_columns_map_to_years_before_current_campaign(self):
        # No Campania rows -> base falls back to ANIO_INICIO_CAMPANIA_ACTUAL (2025)
        ch1, created = campania_historica_desde_columna_excel("CH1")
        self.assertTrue(created)
        self.assertEqual(ch1.anio_inicio, 2024)
        self.assertEqual(ch1.codigo, "CH1")

        ch3, _ = campania_historica_desde_columna_excel("CH3")
        self.assertEqual(ch3.anio_inicio, 2022)
        self.assertEqual(ch3.codigo, "CH3")

    def test_mapping_is_idempotent_with_backfilled_rows(self):
        ch1, created = campania_historica_desde_columna_excel("CH1")
        self.assertTrue(created)

        again, created = campania_historica_desde_columna_excel("CH1")
        self.assertFalse(created)
        self.assertEqual(ch1.pk, again.pk)
        self.assertEqual(CampaniaHistorica.objects.count(), 1)

    def test_mapping_uses_c1_fecha_inicio_when_available(self):
        Campania.objects.create(
            codigo="C1", orden=1, fecha_inicio=date(2026, 7, 1)
        )
        ch1, _ = campania_historica_desde_columna_excel("CH1")
        self.assertEqual(ch1.anio_inicio, 2025)

    def test_mapping_reuses_existing_row_for_the_same_year(self):
        # A producer-loaded campaign for the same year must be reused,
        # keeping HistorialLoteCultivo references consistent.
        existente = CampaniaHistorica.objects.create(
            codigo="CH2024", anio_inicio=2024
        )
        ch1, created = campania_historica_desde_columna_excel("CH1")
        self.assertFalse(created)
        self.assertEqual(ch1.pk, existente.pk)
