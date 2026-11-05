import unittest

from postgres_model_usage import PostgresModelUsageLedger, _settlement


class PostgresModelUsageSettlementTests(unittest.TestCase):
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

    def test_unreserved_non_cache_event_is_rejected(self):
        with self.assertRaises(ValueError):
            PostgresModelUsageLedger(None).record("task", "P1", "deepseek-v4-pro", "low", 1, "accepted")


if __name__ == "__main__":
    unittest.main()
