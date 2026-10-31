import tempfile
import unittest
from pathlib import Path

from model_usage import ModelBudgetExceeded, ModelUsageLedger


class ModelUsageLedgerTests(unittest.TestCase):
    def test_peak_estimate_uses_uncached_peak_prices_and_fails_closed_for_unknown_model(self):
        estimate = ModelUsageLedger.estimate_peak_cost_cny("deepseek-v4-pro", 5000, 4200)
        self.assertAlmostEqual(estimate, 0.2003)
        with self.assertRaisesRegex(ModelBudgetExceeded, "价格未配置"):
            ModelUsageLedger.estimate_peak_cost_cny("unlisted-model", 5000, 4200)

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
            self.assertEqual(summary["billable_calls"], 1)
            self.assertEqual(summary["output_tokens"], 50)
            self.assertEqual(summary["reasoning_tokens"], 30)
            self.assertAlmostEqual(ledger.peak_cost_cny("T1"), (40 * 0.4 + 60 * 11.5 + 50 * 34.0) / 1_000_000)

    def test_detailed_summary_groups_actual_usage_and_keeps_unknown_failures_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ModelUsageLedger(Path(directory) / "usage.sqlite3")
            ledger.record("T2", "P5", "deepseek-flash", "none", 1, "accepted", {
                "prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200,
                "completion_tokens_details": {"reasoning_tokens": 30},
            })
            ledger.record("T2", "P8", "deepseek-v4-pro", "low", 1, "truncated", {
                "prompt_tokens": 500, "completion_tokens": 3200, "total_tokens": 3700,
                "completion_tokens_details": {"reasoning_tokens": 3200},
            }, {"max_tokens": 3200})
            ledger.record("T2", "P8", "deepseek-v4-pro", "low", 2, "transport_error", {})
            result = ledger.detailed_summary("T2")
            self.assertEqual(result["stages"]["P5"]["total_tokens"], 200)
            self.assertEqual(result["stages"]["P5"]["reasoning_tokens"], 30)
            self.assertEqual(result["stages"]["P8"]["reported_calls"], 1)
            self.assertEqual(result["stages"]["P8"]["truncated_calls"], 1)
            self.assertEqual(result["stages"]["P8"]["unknown_usage_calls"], 1)
            self.assertEqual(result["total"]["total_tokens"], 3900)

    def test_pro_guard_stops_before_next_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ModelUsageLedger(Path(directory) / "usage.sqlite3")
            ledger.record("T1", "P8", "deepseek-v4-pro", "high", 1, "accepted", {"completion_tokens": 80, "total_tokens": 100})
            with self.assertRaisesRegex(ModelBudgetExceeded, "Pro 输出"):
                ledger.guard("T1", "deepseek-v4-pro", {"pro_max_output_tokens": 100}, next_output_tokens=30)
            with self.assertRaisesRegex(ModelBudgetExceeded, "Pro 付费调用次数"):
                ledger.guard("T1", "deepseek-v4-pro", {"pro_max_calls": 1})
            with self.assertRaisesRegex(ModelBudgetExceeded, "Pro 总"):
                ledger.guard("T1", "deepseek-v4-pro", {"pro_max_total_tokens": 100})
            with self.assertRaisesRegex(ModelBudgetExceeded, "任务下一次"):
                ledger.guard("T1", "deepseek-flash", {"task_max_total_tokens": 120}, next_input_tokens=10, next_output_tokens=20)
            with self.assertRaisesRegex(ModelBudgetExceeded, "费用上限"):
                ledger.guard("T1", "deepseek-v4-pro", {"task_max_cost_cny": 0.001}, next_input_tokens=100, next_output_tokens=100)

    def test_pro_total_tokens_reserves_next_request(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ModelUsageLedger(Path(directory) / "usage.sqlite3")
            ledger.record("T1", "P1", "deepseek-v4-pro", "low", 1, "accepted", {"prompt_tokens": 400, "completion_tokens": 100, "total_tokens": 500})
            with self.assertRaises(ModelBudgetExceeded):
                ledger.guard("T1", "deepseek-v4-pro", {"pro_max_total_tokens": 600}, next_input_tokens=80, next_output_tokens=50)
            ledger.guard("T1", "deepseek-flash", {"pro_max_output_tokens": 1})


if __name__ == "__main__":
    unittest.main()
