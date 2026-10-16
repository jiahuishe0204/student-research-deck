import os
import tempfile
import unittest
from pathlib import Path

from scf_app import build_workflow


class ScfAppTests(unittest.TestCase):
    def test_builds_existing_workflow_without_model_call(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {"DATABASE_URL": "postgresql://placeholder", "DEEPSEEK_API_KEY": "placeholder", "SCF_USAGE_DB_PATH": os.path.join(temp_dir, "usage.sqlite3")}
            workflow = build_workflow(root, env)
            self.assertIn("P1", workflow.stage_prompts)
            self.assertIn("P9", workflow.stage_prompts)


if __name__ == "__main__":
    unittest.main()
