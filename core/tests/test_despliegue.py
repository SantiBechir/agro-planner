from django.test import TestCase
from unittest.mock import patch
from core.management.commands.deploy_release import Command as DeployReleaseCommand


class DeployReleaseCommandTest(TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("core.management.commands.deploy_release.call_command")
    def test_release_migrates_and_loads_input_v51(self, call_command_mock):
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
        self.assertEqual(
            call_command_mock.call_args_list[2].args[0],
            "cargar_input",
        )
        self.assertTrue(
            call_command_mock.call_args_list[2].args[1]
            .replace("\\", "/")
            .endswith("docs/Input v5.1.xlsx")
        )

    @patch("core.management.commands.deploy_release.call_command", side_effect=SystemExit(1))
    def test_inconsistent_models_stop_release_before_database_writes(self, call_command_mock):
        with self.assertRaises(SystemExit):
            DeployReleaseCommand().handle()
        call_command_mock.assert_called_once_with("makemigrations", check=True, dry_run=True, interactive=False)
