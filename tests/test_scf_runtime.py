import unittest

from scf_runtime import run_claimed_stage


class Cursor:
    def __init__(self):
        self.calls = 0

    def execute(self, sql, params):
        self.calls += 1

    def fetchone(self):
        return ("TASK-1",) if self.calls == 1 else None


class Connection:
    def __init__(self):
        self._cursor = Cursor()

    def cursor(self):
        return self._cursor

    def commit(self):
        pass


class ScfRuntimeTests(unittest.TestCase):
    def test_executor_runs_after_claim(self):
        result = run_claimed_stage(
            Connection(),
            {"task_id": "TASK-1", "stage": "P1", "payload": {"topic": "x"}},
            lambda event: {"received_topic": event["payload"]["topic"]},
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["result"]["received_topic"], "x")


if __name__ == "__main__":
    unittest.main()
