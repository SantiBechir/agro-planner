from django.test import TestCase
from unittest.mock import patch
from core.management.commands.deploy_release import Command as DeployReleaseCommand


class DeployReleaseCommandTest(TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("core.management.commands.deploy_release.call_command")
    def test_release_only_migrates_without_importing_global_or_personal_data(self, call_command_mock):
        DeployReleaseCommand().handle()

        self.assertEqual(call_command_mock.call_args_list[0].args, ("makemigrations",))
        self.assertEqual(
            call_command_mock.call_args_list[0].kwargs,
            {"check": True, "dry_run": True, "interactive": False},
        )
        self.assertEqual(call_command_mock.call_args_list[1].args, ("migrate",))
        self.assertEqual(
            call_command_mock.call_args_list[1].kwargs,
            {"interactive": False},
        )
        self.assertEqual(call_command_mock.call_count, 2)

    @patch("core.management.commands.deploy_release.call_command", side_effect=SystemExit(1))
    def test_inconsistent_models_stop_release_before_database_writes(self, call_command_mock):
        with self.assertRaises(SystemExit):
            DeployReleaseCommand().handle()
        call_command_mock.assert_called_once_with("makemigrations", check=True, dry_run=True, interactive=False)
