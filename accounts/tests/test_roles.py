from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from accounts.roles import EDITOR_ROLE, READER_ROLE, set_functional_role, sync_functional_roles


User = get_user_model()


class FunctionalRoleSyncTest(TestCase):
    def test_post_migrate_creates_both_groups_automatically(self):
        self.assertTrue(Group.objects.filter(name=EDITOR_ROLE).exists())
        self.assertTrue(Group.objects.filter(name=READER_ROLE).exists())

    def test_sync_waits_until_all_core_permissions_exist(self):
        Group.objects.filter(name__in=(EDITOR_ROLE, READER_ROLE)).delete()
        Permission.objects.filter(
            content_type__app_label="core", codename="view_lote"
        ).delete()

        self.assertFalse(sync_functional_roles())
        self.assertFalse(
            Group.objects.filter(name__in=(EDITOR_ROLE, READER_ROLE)).exists()
        )

    def test_sync_creates_expected_permissions_and_excludes_planning_mutation(self):
        Group.objects.filter(name__in=(EDITOR_ROLE, READER_ROLE)).delete()
        self.assertTrue(sync_functional_roles())

        reader = Group.objects.get(name=READER_ROLE)
        editor = Group.objects.get(name=EDITOR_ROLE)
        reader_codes = set(reader.permissions.filter(content_type__app_label="core").values_list("codename", flat=True))
        editor_codes = set(editor.permissions.filter(content_type__app_label="core").values_list("codename", flat=True))

        all_view_codes = set(
            Permission.objects.filter(
                content_type__app_label="core", codename__startswith="view_"
            ).values_list("codename", flat=True)
        )
        self.assertEqual(reader_codes, all_view_codes | {"add_planificacion"})
        self.assertTrue({"add_lote", "change_costo", "delete_cultivo"} <= editor_codes)
        self.assertTrue(all_view_codes <= editor_codes)
        self.assertNotIn("change_planificacion", editor_codes)
        self.assertNotIn("delete_planificacion", editor_codes)
        self.assertNotIn("add_asignacionloteslot", editor_codes)

    def test_sync_is_idempotent_removes_stale_core_permissions_and_preserves_external(self):
        sync_functional_roles()
        reader = Group.objects.get(name=READER_ROLE)
        stale = Permission.objects.get(
            content_type__app_label="core", codename="delete_planificacion"
        )
        external = Permission.objects.get(
            content_type__app_label="auth", codename="view_group"
        )
        reader.permissions.add(stale, external)

        sync_functional_roles()
        first_ids = set(reader.permissions.values_list("pk", flat=True))
        sync_functional_roles()
        second_ids = set(reader.permissions.values_list("pk", flat=True))

        self.assertEqual(first_ids, second_ids)
        self.assertNotIn(stale.pk, second_ids)
        self.assertIn(external.pk, second_ids)

    def test_role_mapping_removes_other_functional_role_only(self):
        user = User.objects.create_user(
            email="roles@example.com",
            first_name="Rita",
            last_name="Roles",
            password="una-clave-segura",
        )
        unrelated = Group.objects.create(name="Grupo externo")
        user.groups.add(unrelated)
        set_functional_role(user, EDITOR_ROLE)
        set_functional_role(user, READER_ROLE)

        self.assertEqual(user.functional_role, READER_ROLE)
        self.assertTrue(user.groups.filter(pk=unrelated.pk).exists())
