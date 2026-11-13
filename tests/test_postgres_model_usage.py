import unittest
from datetime import datetime, timezone

from postgres_model_usage import PostgresModelUsageLedger, _settlement
from model_usage import ModelUsageLedger


class PostgresModelUsageSettlementTests(unittest.TestCase):
    def test_peak_valley_schedule_and_request_timeout_boundary(self):
        # Wednesday 09:00 and 14:00 Beijing are peak starts; weekend and
        # ordinary non-peak hours use the valley multiplier.
        self.assertEqual(ModelUsageLedger.peak_multiplier(datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc)), 1.0)
        self.assertEqual(ModelUsageLedger.peak_multiplier(datetime(2026, 11, 11, 4, 30, tzinfo=timezone.utc)), 0.5)
        self.assertEqual(ModelUsageLedger.peak_multiplier(datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)), 0.5)
        # Wednesday 08:59:30 Beijing: 60 seconds reaches 09:00, 29 does not.
        valley_edge = datetime(2026, 11, 11, 0, 59, 30, tzinfo=timezone.utc)
        self.assertEqual(ModelUsageLedger.peak_multiplier(valley_edge, 60), 1.0)
        self.assertEqual(ModelUsageLedger.peak_multiplier(valley_edge, 29), 0.5)
    def test_billable_usage_is_settled_regardless_of_status(self):
        self.assertEqual(_settlement("http_error", {"status": 500}, True), "settled")
        self.assertEqual(_settlement("accepted", {}, True), "settled")

    def test_definitive_request_rejection_releases_reservation(self):
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                self.assertEqual(_settlement("http_error", {"status": status}, False), "released")

    def test_ambiguous_http_and_transport_errors_keep_reservation(self):
        for status in (408, 409, 425, 429, 500, 502, 503, None):
            with self.subTest(status=status):
                self.assertEqual(_settlement("http_error", {"status": status}, False), "unknown")
        self.assertEqual(_settlement("transport_error", {}, False), "unknown")
        self.assertEqual(_settlement("empty_output", {}, False), "unknown")

    def test_cache_events_are_non_billable_and_known(self):
        self.assertEqual(_settlement("cache_hit", {}, False), "settled")
        self.assertEqual(_settlement("cache_rejected", {}, False), "settled")

    def test_settled_cost_uses_reported_cache_mix_not_all_misses(self):
        prices = {"deepseek-v4-flash": {"cache_hit": 0.1, "cache_miss": 2.0, "output": 5.0}}
        usage = {"prompt_tokens": 1000, "completion_tokens": 200,
                 "prompt_cache_hit_tokens": 700, "prompt_cache_miss_tokens": 200}
        cost = ModelUsageLedger.usage_cost_cny("deepseek-v4-flash", usage, prices)
        self.assertAlmostEqual(cost, (700 * .1 + 300 * 2 + 200 * 5) / 1_000_000)

    def test_unknown_price_model_fails_closed(self):
        with self.assertRaisesRegex(Exception, "费率未配置"):
            ModelUsageLedger.usage_cost_cny("unlisted", {"prompt_tokens": 1})

    def test_explicit_peak_rates_drive_reservation_and_unknown_model_fails_closed(self):
        peak_created_at = datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc)
        class Cursor:
            def __init__(self): self.calls = []; self.last = ""
            def execute(self, sql, params=()): self.calls.append((sql, params)); self.last = sql
            def fetchone(self):
                if "INSERT INTO model_usage_attempts" in self.last: return ("request",)
                return None
            def fetchall(self): return []
        class Connection:
            def __init__(self): self.cur = Cursor()
            def cursor(self): return self.cur
            def commit(self): pass
            def rollback(self): pass
        prices = {"deepseek-v4-flash": {"cache_hit": .1, "cache_miss": 3.0, "output": 7.0}}
        connection = Connection()
        ledger = PostgresModelUsageLedger(connection, prices, clock=lambda: peak_created_at)
        ledger.reserve_attempt("TASK-1", "00000000-0000-0000-0000-000000000001", 1,
                               "P8", "deepseek-v4-flash", "low", {}, 1000, 500,
                               request_timeout_seconds=90)
        insert_params = next(params for sql, params in connection.cur.calls if "INSERT INTO model_usage_attempts" in sql)
        self.assertAlmostEqual(float(insert_params[6]), (1000 * 3 + 500 * 7) / 1_000_000)
        valley_at = datetime(2026, 11, 11, 4, 30, tzinfo=timezone.utc)
        valley_connection = Connection()
        PostgresModelUsageLedger(valley_connection, prices, clock=lambda: valley_at).reserve_attempt(
            "TASK-1", "00000000-0000-0000-0000-000000000002", 1,
            "P8", "deepseek-v4-flash", "low", {}, 1000, 500,
            request_timeout_seconds=90,
        )
        valley_params = next(params for sql, params in valley_connection.cur.calls
                             if "INSERT INTO model_usage_attempts" in sql)
        self.assertAlmostEqual(float(valley_params[6]), .5 * (1000 * 3 + 500 * 7) / 1_000_000)
        with self.assertRaisesRegex(Exception, "价格未配置"):
            ModelUsageLedger.estimate_peak_cost_cny("unlisted", 1000, 500, prices)

    def test_unclassified_prompt_tokens_are_charged_as_cache_misses(self):
        prices = {"deepseek-v4-flash": {"cache_hit": 0, "cache_miss": 2, "output": 5}}
        usage = {"prompt_tokens": 1000, "completion_tokens": 0,
                 "prompt_cache_hit_tokens": 700, "prompt_cache_miss_tokens": 100}
        self.assertAlmostEqual(ModelUsageLedger.usage_cost_cny("deepseek-v4-flash", usage, prices), .0006)

    def test_cache_only_record_is_inserted_without_reservation(self):
        class Cursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, params=()):
                self.calls.append((sql, params))

        class Connection:
            def __init__(self):
                self.cur = Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cur

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        connection = Connection()
        ledger = PostgresModelUsageLedger(connection)
        request_id = ledger.record("task-1", "P4", "deepseek-v4-flash", "low", 0, "cache_hit")
        self.assertTrue(request_id)
        insert_sql, params = connection.cur.calls[0]
        self.assertIn("'settled',0,0", insert_sql)
        self.assertEqual(params[1:4], ("task-1", "P4", "deepseek-v4-flash"))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_postgres_settlement_writes_cache_adjusted_actual_cost(self):
        peak_created_at = datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc)
        class Cursor:
            def __init__(self):
                self.calls = []
            def execute(self, sql, params=()):
                self.calls.append((sql, params))
            def fetchone(self):
                return ("TASK-1", "deepseek-v4-flash", "reserved", peak_created_at)
        class Connection:
            def __init__(self):
                self.cur = Cursor()
            def cursor(self): return self.cur
            def commit(self): pass
            def rollback(self): pass
        connection = Connection()
        prices = {"deepseek-v4-flash": {"cache_hit": 0.1, "cache_miss": 2.0, "output": 5.0}}
        ledger = PostgresModelUsageLedger(connection, prices, clock=lambda: peak_created_at)
        ledger.record_attempt("TASK-1", "00000000-0000-0000-0000-000000000001", 1,
                              "accepted", {"prompt_tokens": 1000, "completion_tokens": 200,
                              "prompt_cache_hit_tokens": 700, "prompt_cache_miss_tokens": 200})
        update_params = connection.cur.calls[-2][1]
        self.assertEqual(update_params[0], "settled")
        self.assertAlmostEqual(float(update_params[2]), (700 * .1 + 300 * 2 + 200 * 5) / 1_000_000)
        self.assertEqual(update_params[5:8], (1200, 700, 200))

    def test_settlement_multiplier_uses_attempt_creation_time_not_completion(self):
        valley_created_at = datetime(2026, 11, 11, 4, 30, tzinfo=timezone.utc)
        class Cursor:
            def __init__(self): self.calls = []
            def execute(self, sql, params=()): self.calls.append((sql, params))
            def fetchone(self): return ("TASK-1", "deepseek-v4-flash", "reserved", valley_created_at)
        class Connection:
            def __init__(self): self.cur = Cursor()
            def cursor(self): return self.cur
            def commit(self): pass
            def rollback(self): pass
        prices = {"deepseek-v4-flash": {"cache_hit": .1, "cache_miss": 2, "output": 5}}
        connection = Connection()
        PostgresModelUsageLedger(connection, prices).record_attempt(
            "TASK-1", "00000000-0000-0000-0000-000000000001", 1, "accepted",
            {"prompt_tokens": 1000, "completion_tokens": 200,
             "prompt_cache_hit_tokens": 700, "prompt_cache_miss_tokens": 200},
        )
        params = connection.cur.calls[-2][1]
        peak_cost = (700 * .1 + 300 * 2 + 200 * 5) / 1_000_000
        self.assertAlmostEqual(float(params[2]), peak_cost * .5)

    def test_unreserved_non_cache_event_is_rejected(self):
        with self.assertRaises(ValueError):
            PostgresModelUsageLedger(None).record("task", "P1", "deepseek-v4-pro", "low", 1, "accepted")


if __name__ == "__main__":
    unittest.main()
