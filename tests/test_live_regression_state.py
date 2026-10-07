import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.run_live_regression import save_resume_state


class LiveRegressionStateTests(unittest.TestCase):
    def test_resume_state_is_private_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("tests.run_live_regression.PRIVATE_STATE_DIR", Path(directory)):
                path = save_resume_state("http://127.0.0.1:4180", "topic", "fast", "TASK-123", "secret-token")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["task_id"], "TASK-123")
            self.assertEqual(saved["owner_token"], "secret-token")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
