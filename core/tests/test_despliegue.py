from django.test import TestCase
from unittest.mock import patch
from core.management.commands.deploy_release import Command as DeployReleaseCommand


class DeployReleaseCommandTest(TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("core.management.commands.deploy_release.call_command")
    def test_release_migrates_and_loads_input_v51(self, call_command_mock):
        DeployReleaseCommand().handle()

        self.assertEqual(call_command_mock.call_args_list[0].args, ("migrate",))
        self.assertEqual(
            call_command_mock.call_args_list[0].kwargs,
            {"interactive": False},
        )
        self.assertEqual(
            call_command_mock.call_args_list[1].args[0],
            "cargar_input",
        )
        self.assertTrue(
            call_command_mock.call_args_list[1].args[1]
            .replace("\\", "/")
            .endswith("docs/Input v5.1.xlsx")
        )
