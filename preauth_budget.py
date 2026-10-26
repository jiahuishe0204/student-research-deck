"""Atomic PostgreSQL reservations for the shared anonymous P1 daily budget."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_UP
import uuid

from model_usage import ModelBudgetExceeded


class DailyBudgetExceeded(ModelBudgetExceeded):
    pass


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("预算金额无效") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("预算金额必须是非负有限数")
    return amount.quantize(Decimal("0.000001"), rounding=ROUND_UP)


class PostgresPreAuthDailyBudget:
    """Shared all-visitor budget, safe across concurrent SCF instances.

    The caller must pass a connection to the same managed PostgreSQL database
    used by all SCF instances. Each method owns and commits its transaction.
    Uncertain provider outcomes remain reserved for the rest of that day.
    """

    TIMEZONE = "Asia/Shanghai"

    def __init__(self, connection, daily_limit_cny=1.0):
        self.connection = connection
        self.daily_limit_cny = _money(daily_limit_cny)
        if self.daily_limit_cny <= 0:
            raise ValueError("每日总预算必须大于零")

    def reserve_attempt(self, request_id, attempt, amount_cny):
        request_id = str(uuid.UUID(str(request_id)))
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 100:
            raise ValueError("模型尝试次数无效")
        amount = _money(amount_cny)
        if amount <= 0:
            raise ValueError("预留金额必须大于零")

        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date")
            budget_day = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO preauth_daily_budgets (budget_day,limit_cny)
                     VALUES (%s,%s) ON CONFLICT (budget_day) DO NOTHING""",
                (budget_day, self.daily_limit_cny),
            )
            cursor.execute(
                """SELECT limit_cny,reserved_cny FROM preauth_daily_budgets
                     WHERE budget_day=%s FOR UPDATE""", (budget_day,),
            )
            daily = cursor.fetchone()
            if not daily:
                raise RuntimeError("每日预算账本初始化失败")
            limit, reserved_total = _money(daily[0]), _money(daily[1])
            cursor.execute(
                """SELECT budget_day,reserved_cny,state FROM preauth_budget_reservations
                     WHERE request_id=%s AND attempt=%s FOR UPDATE""",
                (request_id, attempt),
            )
            existing = cursor.fetchone()
            if existing:
                if existing[0] != budget_day:
                    raise DailyBudgetExceeded("该模型尝试已归属前一自然日，请创建新的请求")
                if existing[2] != "reserved":
                    raise DailyBudgetExceeded("该模型尝试已经结算或费用状态未知，已拒绝重复调用")
                previous = _money(existing[1])
            else:
                previous = Decimal("0")
            next_reservation = max(previous, amount)
            increase = next_reservation - previous
            if reserved_total + increase > limit:
                raise DailyBudgetExceeded("登录前意图识别已达到全站每日费用上限")
            if existing:
                cursor.execute(
                    """UPDATE preauth_budget_reservations
                          SET reserved_cny=%s,state='reserved',updated_at=NOW()
                        WHERE request_id=%s AND attempt=%s""",
                    (next_reservation, request_id, attempt),
                )
            else:
                cursor.execute(
                    """INSERT INTO preauth_budget_reservations
                          (request_id,attempt,budget_day,reserved_cny,state)
                        VALUES (%s,%s,%s,%s,'reserved')""",
                    (request_id, attempt, budget_day, next_reservation),
                )
            if increase:
                cursor.execute(
                    """UPDATE preauth_daily_budgets
                          SET reserved_cny=reserved_cny+%s,updated_at=NOW()
                        WHERE budget_day=%s""", (increase, budget_day),
                )
            self.connection.commit()
            return {"budget_day": budget_day, "reserved_cny": next_reservation, "daily_limit_cny": limit}
        except Exception:
            self.connection.rollback()
            raise

    def settle_attempt(self, request_id, attempt, actual_cost_cny=None):
        """Settle known usage; keep the reservation intact if billing is unknown."""
        request_id = str(uuid.UUID(str(request_id)))
        actual = None if actual_cost_cny is None else _money(actual_cost_cny)
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """SELECT budget_day FROM preauth_budget_reservations
                     WHERE request_id=%s AND attempt=%s""", (request_id, attempt),
            )
            day_row = cursor.fetchone()
            if not day_row:
                raise RuntimeError("找不到对应的每日预算预留")
            budget_day = day_row[0]
            cursor.execute(
                "SELECT budget_day FROM preauth_daily_budgets WHERE budget_day=%s FOR UPDATE",
                (budget_day,),
            )
            if not cursor.fetchone():
                raise RuntimeError("找不到每日预算总账")
            cursor.execute(
                """SELECT reserved_cny,state FROM preauth_budget_reservations
                     WHERE request_id=%s AND attempt=%s FOR UPDATE""", (request_id, attempt),
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("预算预留在结算期间消失")
            reserved = _money(row[0])
            if row[1] != "reserved":
                self.connection.commit()
                return reserved
            if actual is None:
                cursor.execute(
                    """UPDATE preauth_budget_reservations
                          SET state='unknown',updated_at=NOW()
                        WHERE request_id=%s AND attempt=%s""", (request_id, attempt),
                )
                amount_to_keep = reserved
            else:
                amount_to_keep = actual
                cursor.execute(
                    """UPDATE preauth_budget_reservations
                          SET reserved_cny=%s,settled_cny=%s,state='settled',updated_at=NOW()
                        WHERE request_id=%s AND attempt=%s""", (actual, actual, request_id, attempt),
                )
                cursor.execute(
                    """UPDATE preauth_daily_budgets
                          SET reserved_cny=GREATEST(0,reserved_cny-%s),updated_at=NOW()
                        WHERE budget_day=%s""", (reserved - amount_to_keep, budget_day),
                )
            self.connection.commit()
            return amount_to_keep
        except Exception:
            self.connection.rollback()
            raise


__all__ = ["DailyBudgetExceeded", "PostgresPreAuthDailyBudget"]
