import unittest
from types import SimpleNamespace
from unittest.mock import patch

import task_scf_entrypoint
from postgres_model_usage import PostgresModelUsageLedger
from preauth_budget import PostgresPreAuthDailyBudget


class TaskScfEntrypointTests(unittest.TestCase):
    def test_production_worker_builds_workflow_with_shared_postgres_ledgers(self):
        connection = object()
        config = SimpleNamespace(database_url="postgresql://not-used-in-test")
        with patch.object(task_scf_entrypoint, "load_scf_config", return_value=config), \
             patch.object(task_scf_entrypoint, "build_workflow", return_value=object()) as build, \
             patch.object(task_scf_entrypoint, "execute_next_job", return_value={"ok": True}):
            result = task_scf_entrypoint.main_handler({}, connection=connection)

        self.assertEqual(result, {"ok": True})
        kwargs = build.call_args.kwargs
        self.assertIsInstance(kwargs["daily_budget_ledger"], PostgresPreAuthDailyBudget)
        self.assertIs(kwargs["daily_budget_ledger"].connection, connection)
        self.assertIsInstance(kwargs["usage_ledger"], PostgresModelUsageLedger)
        self.assertIs(kwargs["usage_ledger"].connection, connection)

    def test_injected_workflow_is_preserved_for_offline_tests(self):
        connection = object(); injected = object()
        with patch.object(task_scf_entrypoint, "load_scf_config", return_value=SimpleNamespace(database_url="unused")), \
             patch.object(task_scf_entrypoint, "build_workflow") as build, \
             patch.object(task_scf_entrypoint, "execute_next_job", return_value="ok") as execute:
            self.assertEqual(task_scf_entrypoint.main_handler({}, connection=connection, workflow=injected), "ok")
        build.assert_not_called()
        self.assertIs(execute.call_args.args[1], injected)


if __name__ == "__main__":
    unittest.main()
