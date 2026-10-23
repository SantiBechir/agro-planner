"""Aislamiento entre cuentas, comandos y preservación del modelo compartido."""
from copy import deepcopy
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from accounts.roles import EDITOR_ROLE, set_functional_role
from core.models import (
    AsignacionLoteSlot, Campania, ConfiguracionCultivoUsuario, Costo, Cultivo,
    HistorialLoteCultivo, LimiteSuperficieCultivoCampania, Lote, Planificacion,
    SetupCultivo, TipoCosto, TipoSuelo,
)
from core.services.costos import actualizar_costos, consultar_costos
from core.services.economic_indicators import build_economic_indicators
from core.services.input_v51 import (
    InputValidationError, initialize_model_v51, persist_input_v51, read_and_validate_input_v51,
)
from core.services.legacy import asignar_datos_legacy
from core.services.lotes import crear_lote
from core.services.optimization_inputs import build_pyomo_input_data
from core.services.planificaciones import solicitar_planificacion
from core.services.solver import run_optimization
from .test_solver_v51 import example_data


def cuenta(email):
    user = get_user_model().objects.create_user(email=email, first_name="Test", last_name="Owner", is_staff=True)
    set_functional_role(user, EDITOR_ROLE)
    return user


class UserSnapshotTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = read_and_validate_input_v51(settings.BASE_DIR / "docs" / "Input v5.1.xlsx")
        initialize_model_v51(cls.data)
        cls.one = cuenta("one@tenant.test")
        cls.two = cuenta("two@tenant.test")
        persist_input_v51(cls.data, cls.one)
        persist_input_v51(cls.data, cls.two)

    def test_two_snapshots_share_rules_but_have_distinct_private_rows(self):
        self.assertEqual(Cultivo.objects.count(), len(self.data.cultivos))
        self.assertEqual(Lote.objects.filter(usuario=self.one).count(), len(self.data.lotes))
        self.assertEqual(Lote.objects.filter(usuario=self.two).count(), len(self.data.lotes))
        self.assertEqual(Costo.objects.filter(usuario=self.one).count(), len(self.data.costos))
        for (crop, campaign), (minimum, maximum) in self.data.limites.items():
            obj = LimiteSuperficieCultivoCampania.objects.get(usuario=self.one, cultivo__codigo=crop, campania__codigo=campaign)
            self.assertEqual((obj.min_ha, obj.max_ha), (minimum, maximum))
        self.assertEqual(HistorialLoteCultivo.objects.filter(lote__usuario=self.one).count(), len(self.data.historial))
        self.assertTrue(Costo.objects.filter(usuario=self.one, tipo_costo__codigo="frc").exists())

    def test_reimport_is_idempotent_and_only_changes_its_owner(self):
        before = list(Costo.objects.filter(usuario=self.two).order_by("pk").values())
        lot = Lote.objects.filter(usuario=self.one).first()
        lot.habilitado = False
        lot.save()
        changed = deepcopy(self.data)
        key = next(iter(changed.costos))
        changed.costos[key] += 123
        counts = (Lote.objects.count(), Costo.objects.count(), HistorialLoteCultivo.objects.count())
        persist_input_v51(changed, self.one)
        persist_input_v51(changed, self.one)
        lot.refresh_from_db()
        self.assertFalse(lot.habilitado)
        self.assertEqual(before, list(Costo.objects.filter(usuario=self.two).order_by("pk").values()))
        self.assertEqual(counts, (Lote.objects.count(), Costo.objects.count(), HistorialLoteCultivo.objects.count()))

    def test_global_conflict_rolls_back_initializer_and_personal_import(self):
        changed = deepcopy(self.data)
        changed.setups[next(iter(changed.setups))] += 1
        changed.suelos.append("NEW")
        before = TipoSuelo.objects.count()
        with self.assertRaises(InputValidationError):
            initialize_model_v51(changed)
        self.assertEqual(TipoSuelo.objects.count(), before)
        with self.assertRaises(InputValidationError):
            persist_input_v51(changed, self.one)

    def test_shared_crop_differences_warn_and_preserve_existing_card(self):
        changed = deepcopy(self.data)
        code = changed.cultivos[0]
        changed.parametros_cultivo[code]["duracion_dias"] += 1
        before = Cultivo.objects.get(codigo=code).duracion_dias
        stats = initialize_model_v51(changed)
        self.assertTrue(stats.warnings)
        self.assertEqual(Cultivo.objects.get(codigo=code).duracion_dias, before)

    def test_cost_ids_and_economic_indicators_are_private(self):
        other = Costo.objects.filter(usuario=self.two).first()
        old_value = other.valor
        actualizar_costos(self.one, {other.pk: 999})
        other.refresh_from_db()
        self.assertEqual(other.valor, old_value)
        own_ids = set(Costo.objects.filter(usuario=self.one).values_list("pk", flat=True))
        listing = consultar_costos(self.one)
        self.assertTrue(set(obj.pk for obj in listing["page_obj"]) <= own_ids)
        before = build_economic_indicators(self.one)
        Costo.objects.filter(usuario=self.two, tipo_costo__codigo="fsp").update(valor=99999)
        self.assertEqual(before, build_economic_indicators(self.one))

    def test_enabling_a_crop_does_not_enable_it_for_another_user(self):
        crop = Cultivo.objects.first()
        ConfiguracionCultivoUsuario.objects.filter(usuario=self.one, cultivo=crop).update(habilitado_optimizacion=False)
        self.assertNotIn(crop.codigo, build_pyomo_input_data(self.one)["i"])
        self.assertIn(crop.codigo, build_pyomo_input_data(self.two)["i"])
        actualizar_costos(self.one, {}, cultivo_id=crop.pk, habilitar=True)
        self.assertIn(crop.codigo, build_pyomo_input_data(self.one)["i"])

    def test_disabling_from_the_crop_screen_only_changes_its_owner(self):
        crop = Cultivo.objects.first()
        self.client.force_login(self.one)
        self.assertContains(self.client.get(reverse("cultivo_list")), reverse("cultivo_desactivar", args=[crop.pk]))
        self.assertEqual(self.client.get(reverse("cultivo_desactivar", args=[crop.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse("cultivo_desactivar", args=[crop.pk])).status_code, 200)
        self.assertFalse(ConfiguracionCultivoUsuario.objects.get(usuario=self.one, cultivo=crop).habilitado_optimizacion)
        self.assertTrue(ConfiguracionCultivoUsuario.objects.get(usuario=self.two, cultivo=crop).habilitado_optimizacion)

    def test_legacy_costs_are_hidden_and_new_accounts_have_no_enabled_crops(self):
        user = cuenta("empty@tenant.test")
        legacy = Costo.objects.filter(usuario=self.one, lote__isnull=True).first()
        legacy.pk = None
        legacy.usuario = None
        legacy.valor = 99999
        legacy.save()
        self.assertFalse(consultar_costos(user)["page_obj"].object_list.exists())
        self.assertEqual(build_economic_indicators(user), {"margins": [], "break_even": []})
        self.assertEqual(build_pyomo_input_data(user)["i"], [])

    def test_limits_use_html_decimal_points_and_reject_nonfinite_values(self):
        limit = LimiteSuperficieCultivoCampania.objects.filter(usuario=self.one).first()
        limit.min_ha = 12.5
        limit.max_ha = 99.75
        limit.save()
        self.client.force_login(self.one)
        response = self.client.get(reverse("planificacion_list"))
        self.assertContains(response, 'value="12.50"')
        values = {}
        for item in LimiteSuperficieCultivoCampania.objects.filter(usuario=self.one, cultivo=limit.cultivo):
            values[f"min_{item.pk}"] = item.min_ha
            values[f"max_{item.pk}"] = item.max_ha
        values[f"min_{limit.pk}"] = "nan"
        self.client.post(reverse("planificacion_limites_update", args=[limit.cultivo_id]), values, HTTP_HX_REQUEST="true")
        limit.refresh_from_db()
        self.assertEqual(limit.min_ha, 12.5)

    def test_new_lot_has_pending_rental_costs_and_blocks_planning_until_reviewed(self):
        soil = TipoSuelo.objects.first()
        lot = crear_lote(self.one, nombre="Nuevo", ambientes=[(soil.pk, "M", 100)])
        self.assertTrue(Costo.objects.filter(usuario=self.one, lote=lot, configurado=False).exists())
        with self.assertRaisesMessage(ValidationError, "pendientes"):
            solicitar_planificacion(self.one, nombre="No debe omitir arrendamientos")

    def test_admin_and_application_reject_foreign_objects(self):
        foreign_lot = Lote.objects.filter(usuario=self.two).first()
        self.client.force_login(self.one)
        self.assertEqual(self.client.post(reverse("lote_toggle", args=[foreign_lot.pk])).status_code, 404)
        request = RequestFactory().get("/admin/")
        request.user = self.one
        model_admin = admin.site._registry[Costo]
        self.assertFalse(model_admin.get_queryset(request).exclude(usuario=self.one).exists())
        field = model_admin.formfield_for_foreignkey(Costo._meta.get_field("lote"), request)
        self.assertFalse(field.queryset.filter(pk=foreign_lot.pk).exists())
        self.assertFalse(admin.site._registry[SetupCultivo].has_change_permission(request))
        own_cost = Costo.objects.filter(usuario=self.one).first()
        own_cost.lote = foreign_lot
        with self.assertRaises(ValidationError):
            own_cost.save()
        foreign_lot.usuario = self.one
        with self.assertRaises(ValidationError):
            foreign_lot.save()

    def test_cost_uniqueness_including_null_dimensions(self):
        for campaign_null, lot_null in ((True, True), (False, True), (False, False)):
            obj = Costo.objects.filter(usuario=self.one, campania__isnull=campaign_null, lote__isnull=lot_null).first()
            obj.pk = None
            with self.subTest(campaign_null=campaign_null, lot_null=lot_null):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    obj.save()

    def test_cli_requires_existing_user_and_validation_never_writes(self):
        path = str(settings.BASE_DIR / "docs" / "Input v5.1.xlsx")
        with self.assertRaises(CommandError):
            call_command("cargar_input", path, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("cargar_input", path, usuario="absent@test.local", stdout=StringIO())
        counts = (Costo.objects.count(), Lote.objects.count())
        call_command("cargar_input", path, validar=True, stdout=StringIO())
        self.assertEqual(counts, (Costo.objects.count(), Lote.objects.count()))


class LegacyAssignmentTest(TestCase):
    def setUp(self):
        self.user = cuenta("legacy@test.local")
        self.crop = Cultivo.objects.create(codigo="TRIGO", nombre="Trigo", duracion_dias=120, siembra_inicio=1, siembra_fin=60, habilitado_optimizacion=True)
        self.kind = TipoCosto.objects.create(codigo="fsp")
        self.campaign = Campania.objects.create(codigo="C1", orden=1)
        self.cost = Costo.objects.create(cultivo=self.crop, tipo_costo=self.kind, valor=123)
        self.limit = LimiteSuperficieCultivoCampania.objects.create(cultivo=self.crop, campania=self.campaign, min_ha=5, max_ha=100)

    def test_assignment_preserves_values_and_is_repeatable(self):
        self.assertEqual(asignar_datos_legacy(self.user), (1, 1))
        self.assertEqual(asignar_datos_legacy(self.user), (0, 0))
        self.cost.refresh_from_db()
        self.limit.refresh_from_db()
        self.assertEqual((self.cost.usuario_id, self.cost.valor), (self.user.pk, 123))
        self.assertEqual((self.limit.usuario_id, self.limit.min_ha, self.limit.max_ha), (self.user.pk, 5, 100))
        self.assertTrue(ConfiguracionCultivoUsuario.objects.get(usuario=self.user, cultivo=self.crop).habilitado_optimizacion)

    def test_conflict_does_not_partially_assign_costs_or_limits(self):
        LimiteSuperficieCultivoCampania.objects.create(usuario=self.user, cultivo=self.crop, campania=self.campaign, min_ha=0, max_ha=50)
        with self.assertRaises(ValidationError):
            asignar_datos_legacy(self.user)
        self.cost.refresh_from_db()
        self.limit.refresh_from_db()
        self.assertIsNone(self.cost.usuario_id)
        self.assertIsNone(self.limit.usuario_id)
        self.assertFalse(ConfiguracionCultivoUsuario.objects.exists())

    def test_duplicate_legacy_costs_abort_without_writes(self):
        Costo.objects.create(cultivo=self.crop, tipo_costo=self.kind, valor=456)
        with self.assertRaises(ValidationError):
            asignar_datos_legacy(self.user)
        self.assertEqual(Costo.objects.filter(usuario__isnull=True).count(), 2)


class InfeasibleSolverTest(TestCase):
    def test_infeasible_result_is_persisted_with_actionable_message(self):
        data = example_data()
        data["maxha_dict"][("MAIN", "C1")] = 99
        user = cuenta("solver@test.local")
        plan = Planificacion.objects.create(usuario=user, nombre="Infactible")
        with patch("core.services.solver.build_pyomo_input_data", return_value=data):
            self.assertFalse(run_optimization(plan.pk))
        plan.refresh_from_db()
        self.assertEqual(plan.estado, Planificacion.Estado.INFACTIBLE)
        self.assertIn("mínimos y máximos", plan.detalle_error)
        self.assertFalse(plan.asignaciones.exists())


class OwnershipMigrationTest(TransactionTestCase):
    def test_existing_economic_values_survive_until_explicit_assignment(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        target = [("core", "0012_limites_superficie_usuario")]
        executor.migrate(target)
        try:
            old = executor.loader.project_state(target).apps
            crop = old.get_model("core", "Cultivo").objects.create(
                codigo="LEGACY", nombre="Legacy", duracion_dias=120,
                siembra_inicio=1, siembra_fin=60, habilitado_optimizacion=True,
            )
            kind = old.get_model("core", "TipoCosto").objects.create(codigo="fsp")
            cost = old.get_model("core", "Costo").objects.create(cultivo=crop, tipo_costo=kind, valor=321)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        migrated = Costo.objects.get(pk=cost.pk)
        self.assertIsNone(migrated.usuario_id)
        self.assertEqual(migrated.valor, 321)
        user = cuenta("migration@test.local")
        call_command("asignar_datos_legacy", usuario=user.email, stdout=StringIO())
        migrated.refresh_from_db()
        self.assertEqual(migrated.usuario_id, user.pk)
        self.assertTrue(ConfiguracionCultivoUsuario.objects.get(usuario=user, cultivo_id=crop.pk).habilitado_optimizacion)
