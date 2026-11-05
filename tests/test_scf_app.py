import os
import tempfile
import unittest
from pathlib import Path

from scf_app import build_queued_stage_dispatcher, build_workflow


class ScfAppTests(unittest.TestCase):
    def test_queued_dispatcher_injects_configured_patsnap_without_network_call(self):
        from patsnap_mcp import PatsnapMCPClient

        env = {
            "PATENT_PROVIDER": "patsnap_mcp_cn",
            "PATSNAP_MCP_API_KEY": "test-secret",
            "PATSNAP_MCP_TIMEOUT_SECONDS": "17",
        }
        dispatcher = build_queued_stage_dispatcher(env)
        pipeline = dispatcher.keywords["research_pipeline_fn"]
        options = dispatcher.keywords["research_pipeline_options"]
        self.assertEqual(pipeline.__name__, "search_and_screen_sources")
        self.assertIsInstance(options["patent_client"], PatsnapMCPClient)
        self.assertEqual(options["patent_client"].timeout, 17)
        self.assertEqual(options["environ"], env)

    def test_queued_dispatcher_fails_closed_when_selected_provider_has_no_key(self):
        with self.assertRaisesRegex(RuntimeError, "PATSNAP_MCP_API_KEY"):
            build_queued_stage_dispatcher({"PATENT_PROVIDER": "patsnap_mcp_cn"})

    def test_queued_dispatcher_does_not_construct_patent_client_without_explicit_selection(self):
        dispatcher = build_queued_stage_dispatcher({})
        self.assertNotIn("patent_client", dispatcher.keywords["research_pipeline_options"])

    def test_builds_existing_workflow_without_model_call(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {"DATABASE_URL": "postgresql://placeholder", "DEEPSEEK_API_KEY": "placeholder", "SCF_USAGE_DB_PATH": os.path.join(temp_dir, "usage.sqlite3")}
            workflow = build_workflow(root, env)
            self.assertIn("P1", workflow.stage_prompts)
            self.assertIn("P9", workflow.stage_prompts)

    def test_injects_shared_daily_budget_without_changing_local_default(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {"DATABASE_URL": "postgresql://placeholder", "DEEPSEEK_API_KEY": "placeholder", "SCF_USAGE_DB_PATH": os.path.join(temp_dir, "usage.sqlite3")}
            ledger = object()
            workflow = build_workflow(root, env, daily_budget_ledger=ledger)
        self.assertIs(workflow.daily_budget_ledger, ledger)


if __name__ == "__main__":
    unittest.main()
