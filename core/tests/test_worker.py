from django.test import TestCase
from io import StringIO
from unittest.mock import patch
from core.models import Planificacion
from core.management.commands.process_optimizations import Command as ProcessOptimizationsCommand


class ProcessOptimizationsCommandTest(TestCase):
    @patch("core.management.commands.process_optimizations.run_optimization")
    def test_solver_failure_is_not_reported_as_success(self, run_optimization_mock):
        planificacion = Planificacion.objects.create(nombre="Planificacion fallida")
        run_optimization_mock.return_value = False
        command = ProcessOptimizationsCommand(stdout=StringIO(), stderr=StringIO())

        processed = command._process_one()

        self.assertFalse(processed)
        run_optimization_mock.assert_called_once_with(planificacion.id)
        self.assertIn("termino con error", command.stderr.getvalue())
        self.assertNotIn("finalizada", command.stdout.getvalue())
