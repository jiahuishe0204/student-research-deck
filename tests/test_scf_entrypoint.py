import os
import sys
import types
import unittest
from unittest.mock import patch

from scf_entrypoint import _connect_database, main_handler


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
    def test_database_connection_prefers_pure_python_pg8000(self):
        calls = []
        dbapi = types.ModuleType("pg8000.dbapi")
        dbapi.connect = lambda **kwargs: calls.append(kwargs) or "connection"
        pg8000 = types.ModuleType("pg8000")
        pg8000.__path__ = []
        pg8000.dbapi = dbapi
        with patch.dict(sys.modules, {"pg8000": pg8000, "pg8000.dbapi": dbapi}):
            connection = _connect_database(
                "postgresql://research:pa%40ss@db.example:5433/research_db?sslmode=require"
            )
        self.assertEqual(connection, "connection")
        self.assertEqual(calls, [{
            "user": "research",
            "password": "pa@ss",
            "host": "db.example",
            "port": 5433,
            "database": "research_db",
            "ssl_context": True,
        }])

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
