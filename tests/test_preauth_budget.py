from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from preauth_budget import DailyBudgetExceeded, PostgresPreAuthDailyBudget


class Cursor:
    def __init__(self, results=()):
        self.results = iter(results)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return next(self.results)


class Connection:
    def __init__(self, results=()):
        self.cursor_value = Cursor(results)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class PreAuthBudgetTests(unittest.TestCase):
    def test_migration_defines_daily_total_and_idempotent_attempt_reservations(self):
        migration = (Path(__file__).resolve().parents[1] / "migrations" / "008_preauth_daily_budget.sql").read_text(encoding="utf-8")
        self.assertIn("preauth_daily_budgets", migration)
        self.assertIn("PRIMARY KEY (request_id, attempt)", migration)
        self.assertIn("CHECK (reserved_cny >= 0)", migration)

    def test_reservation_is_atomic_and_uses_beijing_calendar_day(self):
        db = Connection([
            (date(2026, 10, 24),),
            (Decimal("1.0"), Decimal("0.75")),
            None,
        ])
        result = PostgresPreAuthDailyBudget(db).reserve_attempt(
            "00000000-0000-0000-0000-000000000001", 1, 0.20,
        )
        self.assertEqual(result["budget_day"], date(2026, 10, 24))
        sql = "\n".join(statement for statement, _ in db.cursor_value.statements)
        self.assertIn("Asia/Shanghai", sql)
        self.assertIn("FOR UPDATE", sql)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)

    def test_reservation_fails_closed_when_daily_total_would_exceed_one_yuan(self):
        db = Connection([
            (date(2026, 10, 24),),
            (Decimal("1.0"), Decimal("0.90")),
            None,
        ])
        with self.assertRaisesRegex(DailyBudgetExceeded, "每日费用上限"):
            PostgresPreAuthDailyBudget(db).reserve_attempt(
                "00000000-0000-0000-0000-000000000002", 1, 0.11,
            )
        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)

    def test_unknown_provider_charge_keeps_reservation(self):
        db = Connection([
            (date(2026, 10, 24),),
            (date(2026, 10, 24),),
            (Decimal("0.20"), "reserved"),
        ])
        PostgresPreAuthDailyBudget(db).settle_attempt(
            "00000000-0000-0000-0000-000000000003", 1, None,
        )
        sql = "\n".join(statement for statement, _ in db.cursor_value.statements)
        self.assertIn("state='unknown'", sql)
        self.assertNotIn("SET reserved_cny=GREATEST", sql)
        self.assertEqual(db.commits, 1)

    def test_known_cost_releases_unused_reservation_but_records_actual(self):
        db = Connection([
            (date(2026, 10, 24),),
            (date(2026, 10, 24),),
            (Decimal("0.20"), "reserved"),
        ])
        actual = PostgresPreAuthDailyBudget(db).settle_attempt(
            "00000000-0000-0000-0000-000000000004", 1, 0.08,
        )
        self.assertEqual(actual, Decimal("0.080000"))
        sql = "\n".join(statement for statement, _ in db.cursor_value.statements)
        self.assertIn("settled_cny=%s", sql)
        self.assertIn("reserved_cny=GREATEST", sql)

    def test_actual_over_estimate_is_recorded_and_kept_conservatively(self):
        db = Connection([
            (date(2026, 10, 24),),
            (date(2026, 10, 24),),
            (Decimal("0.10"), "reserved"),
        ])
        actual = PostgresPreAuthDailyBudget(db).settle_attempt(
            "00000000-0000-0000-0000-000000000007", 1, 0.12,
        )
        self.assertEqual(actual, Decimal("0.120000"))
        daily_update = db.cursor_value.statements[-1][1]
        self.assertEqual(daily_update[0], Decimal("-0.020000"))

    def test_invalid_reservation_inputs_are_rejected(self):
        db = Connection()
        budget = PostgresPreAuthDailyBudget(db)
        with self.assertRaises(ValueError):
            budget.reserve_attempt("not-a-uuid", 1, 0.1)
        with self.assertRaises(ValueError):
            budget.reserve_attempt("00000000-0000-0000-0000-000000000005", 0, 0.1)
        with self.assertRaises(ValueError):
            budget.reserve_attempt("00000000-0000-0000-0000-000000000006", 1, -0.1)


if __name__ == "__main__":
    unittest.main()
