import unittest

from scf_config import load_scf_config


class ScfConfigTests(unittest.TestCase):
    def test_loads_without_exposing_values(self):
        config = load_scf_config({"DATABASE_URL": "postgresql://secret", "DEEPSEEK_API_KEY": "key", "MODEL_TASK_MAX_COST_CNY": "3"})
        self.assertEqual(config.task_max_cost_cny, 3.0)
        self.assertEqual(config.task_max_total_tokens, 600000)

    def test_explicit_token_budget_is_preserved(self):
        config = load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key", "MODEL_TASK_MAX_TOTAL_TOKENS": "500000"})
        self.assertEqual(config.task_max_total_tokens, 500000)

    def test_default_model_cost_cap_is_three_yuan(self):
        config = load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key"})
        self.assertEqual(config.task_max_cost_cny, 3.0)

    def test_missing_secret_fails_closed(self):
        with self.assertRaises(RuntimeError):
            load_scf_config({"DATABASE_URL": "postgresql://secret"})

    def test_invalid_budget_fails_closed(self):
        with self.assertRaises(RuntimeError):
            load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key", "MODEL_TASK_MAX_COST_CNY": "0"})


if __name__ == "__main__":
    unittest.main()
