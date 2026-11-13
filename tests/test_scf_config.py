import unittest

from scf_config import load_scf_config


class ScfConfigTests(unittest.TestCase):
    def test_loads_without_exposing_values(self):
        config = load_scf_config({"DATABASE_URL": "postgresql://secret", "DEEPSEEK_API_KEY": "key", "MODEL_TASK_MAX_COST_CNY": "3"})
        self.assertEqual(config.task_max_cost_cny, 3.0)
        self.assertEqual(config.task_max_total_tokens, 3000000)

    def test_explicit_token_budget_is_preserved(self):
        config = load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key", "MODEL_TASK_MAX_TOTAL_TOKENS": "500000"})
        self.assertEqual(config.task_max_total_tokens, 500000)

    def test_default_model_cost_cap_is_three_yuan(self):
        config = load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key"})
        self.assertEqual(config.task_max_cost_cny, 3.0)

    def test_optional_model_price_schedule_is_parsed(self):
        config = load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key",
            "MODEL_PRICES_CNY_PER_MILLION": '{"deepseek-v4-flash":{"cache_hit":0.1,"cache_miss":2.0,"output":5.0}}'})
        self.assertEqual(config.model_prices_cny_per_million["deepseek-v4-flash"]["cache_hit"], 0.1)

    def test_invalid_model_price_schedule_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "MODEL_PRICES_CNY_PER_MILLION 格式无效"):
            load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key",
                             "MODEL_PRICES_CNY_PER_MILLION": '{"model":{"cache_hit":-1}}'})

    def test_missing_secret_fails_closed(self):
        with self.assertRaises(RuntimeError):
            load_scf_config({"DATABASE_URL": "postgresql://secret"})

    def test_invalid_budget_fails_closed(self):
        with self.assertRaises(RuntimeError):
            load_scf_config({"DATABASE_URL": "db", "DEEPSEEK_API_KEY": "key", "MODEL_TASK_MAX_COST_CNY": "0"})


if __name__ == "__main__":
    unittest.main()
