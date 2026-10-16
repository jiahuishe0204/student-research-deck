import os
import unittest

from scf_entrypoint import main_handler


class Cursor:
    def __init__(self):
        self.calls = 0

    def execute(self, sql, params):
        self.calls += 1

    def fetchone(self):
        return ("TASK-1",) if self.calls in (1, 2) else None


class Connection:
    def __init__(self):
        self._cursor = Cursor()

    def cursor(self):
        return self._cursor

    def commit(self):
        pass


class Workflow:
    def create_intent(self, topic, tier):
        return {"topic": topic, "tier": tier}


class ScfEntrypointTests(unittest.TestCase):
    def test_handler_is_scf_compatible_with_injected_dependencies(self):
        old = dict(os.environ)
        try:
            os.environ["DATABASE_URL"] = "postgresql://placeholder"
            os.environ["DEEPSEEK_API_KEY"] = "placeholder"
            result = main_handler(
                {"task_id": "TASK-1", "stage": "P1", "payload": {"topic": "细胞", "tier": "fast"}},
                None,
                connection=Connection(),
                workflow=Workflow(),
            )
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(result["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
