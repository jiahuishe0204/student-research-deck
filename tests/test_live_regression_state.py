import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.run_live_regression import save_resume_state, choose_user_direction


class LiveRegressionStateTests(unittest.TestCase):
    def test_resume_state_is_private_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("tests.run_live_regression.PRIVATE_STATE_DIR", Path(directory)):
                path = save_resume_state("http://127.0.0.1:4180", "topic", "fast", "TASK-123", "secret-token")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["task_id"], "TASK-123")
            self.assertEqual(saved["owner_token"], "secret-token")
            self.assertEqual(saved["selected_direction"], "")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_user_selected_direction_must_uniquely_match_card(self):
        intent = {"need_clarification": True, "topic_breadth": "broad", "direction_options": [
            {"direction_id": "D1", "title": "神经损伤修复"},
            {"direction_id": "D2", "title": "慢性植入神经接口中的导电水凝胶界面"},
        ]}
        self.assertEqual(choose_user_direction(intent, "慢性植入神经接口"), "D2")
        with self.assertRaisesRegex(RuntimeError, "不能代选"):
            choose_user_direction(intent, "")
        with self.assertRaisesRegex(RuntimeError, "无法唯一对应"):
            choose_user_direction(intent, "无线神经调控")


if __name__ == "__main__":
    unittest.main()
