import tempfile
import unittest
from pathlib import Path

from model_usage import ModelBudgetExceeded, ModelUsageLedger


class ModelUsageLedgerTests(unittest.TestCase):
    def test_records_success_failure_and_token_details(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ModelUsageLedger(Path(directory) / "usage.sqlite3")
            ledger.record("T1", "P8", "deepseek-v4-pro", "high", 1, "rejected", {
                "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
                "prompt_cache_hit_tokens": 40, "prompt_cache_miss_tokens": 60,
                "completion_tokens_details": {"reasoning_tokens": 30},
            })
            ledger.record("T1", "P8", "deepseek-v4-pro", "high", 2, "transport_error", {})
            summary = ledger.summary("T1")["deepseek-v4-pro"]
            self.assertEqual(summary["calls"], 2)
            self.assertEqual(summary["output_tokens"], 50)
            self.assertEqual(summary["reasoning_tokens"], 30)

    def test_pro_guard_stops_before_next_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ModelUsageLedger(Path(directory) / "usage.sqlite3")
            ledger.record("T1", "P8", "deepseek-v4-pro", "high", 1, "accepted", {"completion_tokens": 80, "total_tokens": 100})
            with self.assertRaisesRegex(ModelBudgetExceeded, "Pro 输出"):
                ledger.guard("T1", "deepseek-v4-pro", {"pro_max_output_tokens": 100}, next_output_tokens=30)
            with self.assertRaisesRegex(ModelBudgetExceeded, "Pro 调用次数"):
                ledger.guard("T1", "deepseek-v4-pro", {"pro_max_calls": 1})
            with self.assertRaisesRegex(ModelBudgetExceeded, "Pro 总"):
                ledger.guard("T1", "deepseek-v4-pro", {"pro_max_total_tokens": 100})
            with self.assertRaisesRegex(ModelBudgetExceeded, "任务下一次"):
                ledger.guard("T1", "deepseek-flash", {"task_max_total_tokens": 120}, next_input_tokens=10, next_output_tokens=20)
            ledger.guard("T1", "deepseek-flash", {"pro_max_output_tokens": 1})


if __name__ == "__main__":
    unittest.main()
