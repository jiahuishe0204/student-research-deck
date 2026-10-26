import unittest

from scf_claims import CLAIMS_MIGRATION_SQL, claim_stage, finish_stage


class Cursor:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return next(self.results)


class Connection:
    def __init__(self, results):
        self.cursor_value = Cursor(results)
        self.commits = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1


class ScfClaimTests(unittest.TestCase):
    def test_first_worker_claims(self):
        connection = Connection([("TASK-1",)])
        self.assertTrue(claim_stage(connection, "TASK-1", "p1", 1))
        self.assertEqual(connection.commits, 1)

    def test_duplicate_active_claim_is_rejected(self):
        connection = Connection([None, None])
        self.assertFalse(claim_stage(connection, "TASK-1", "P1", 1))
        self.assertEqual(connection.commits, 1)

    def test_migration_has_unique_claim_key(self):
        self.assertIn("PRIMARY KEY (task_id, stage, work_item_id, attempt)", CLAIMS_MIGRATION_SQL)
        self.assertIn("work_item_id TEXT NOT NULL DEFAULT 'main'", CLAIMS_MIGRATION_SQL)
        self.assertIn("lease_token UUID NOT NULL", CLAIMS_MIGRATION_SQL)

    def test_work_item_attempts_are_scoped_independently(self):
        connection = Connection([("TASK-1",)])
        self.assertTrue(claim_stage(connection, "TASK-1", "P8", 1, work_item_id="batch:0002"))
        sql, params = connection.cursor_value.statements[0]
        self.assertIn("ON CONFLICT (task_id, stage, work_item_id, attempt)", sql)
        self.assertEqual(params[2], "batch:0002")

    def test_finish_requires_current_fencing_token_and_work_item(self):
        connection = Connection([("TASK-1",)])
        self.assertTrue(finish_stage(connection, "TASK-1", "P8", 1, "token-current", "succeeded", work_item_id="batch:0002"))
        sql, params = connection.cursor_value.statements[0]
        self.assertIn("lease_token = %s", sql)
        self.assertIn("work_item_id = %s", sql)
        self.assertEqual(params[3], "batch:0002")
        self.assertEqual(params[-1], "token-current")


if __name__ == "__main__":
    unittest.main()
