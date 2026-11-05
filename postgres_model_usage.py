"""Atomic, cross-SCF-instance model cost/token reservations in PostgreSQL."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from model_usage import ModelBudgetExceeded, ModelUsageLedger


def _int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        raise ValueError("模型 Token 数无效")


def _settlement(result_status, detail, has_usage):
    """Return settled/released/unknown without assuming ambiguous HTTP errors are free."""
    if has_usage:
        return "settled"
    if result_status in {"cache_hit", "cache_rejected"}:
        return "settled"
    if result_status == "http_error":
        status = (detail or {}).get("status")
        # These responses reject the request before inference. Timeouts,
        # throttling, conflicts, and all 5xx outcomes remain reserved because
        # the provider may have accepted work before the response failed.
        if status in {400, 401, 403, 404, 422}:
            return "released"
    return "unknown"


class PostgresModelUsageLedger:
    """Shared per-task hard cap, including active reservations and uncertain calls.

    Every reservation locks the task row (or a stable advisory lock for the
    pre-auth pseudo-task), so concurrent P4/P8 jobs cannot all pass against the
    same stale spend total. Unknown network outcomes remain charged at the
    conservative reservation until reconciled.
    """

    def __init__(self, connection):
        self.connection = connection

    def reserve_attempt(self, task_id, request_id, attempt, stage, model, effort,
                        limits, next_input_tokens, next_output_tokens):
        task_id = str(task_id)
        request_id = str(uuid.UUID(str(request_id)))
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 100:
            raise ValueError("模型尝试次数无效")
        input_tokens, output_tokens = _int(next_input_tokens), _int(next_output_tokens)
        reserve_tokens = input_tokens + output_tokens
        reserve_cost = Decimal(str(ModelUsageLedger.estimate_peak_cost_cny(model, input_tokens, output_tokens)))
        cost_limit = Decimal(str((limits or {}).get("task_max_cost_cny", 0) or 0))
        token_limit = int((limits or {}).get("task_max_total_tokens", 0) or 0)
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT task_id FROM research_tasks WHERE task_id=%s FOR UPDATE", (task_id,))
            if not cursor.fetchone():
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (task_id,))
            cursor.execute(
                """SELECT model,budget_state,reserved_cost_cny,actual_cost_cny,
                          reserved_total_tokens,total_tokens,reserved_output_tokens,completion_tokens
                     FROM model_usage_attempts WHERE task_id=%s""", (task_id,),
            )
            rows = cursor.fetchall()
            spent_cost = Decimal("0")
            spent_tokens = 0
            pro_calls, pro_output, pro_tokens = 0, 0, 0
            for row in rows:
                row_model, state = row[0], row[1]
                active = state in {"reserved", "unknown"}
                spent_cost += Decimal(str(row[2] if active else row[3] or 0))
                spent_tokens += int(row[4] if active else row[5] or 0)
                if row_model == "deepseek-v4-pro" and state != "released":
                    pro_calls += 1
                    pro_output += int(row[6] if active else row[7] or 0)
                    pro_tokens += int(row[4] if active else row[5] or 0)
            if cost_limit > 0 and spent_cost + reserve_cost > cost_limit:
                raise ModelBudgetExceeded("任务下一次请求将超过共享费用上限 %.3f 元" % cost_limit)
            if token_limit > 0 and spent_tokens + reserve_tokens > token_limit:
                raise ModelBudgetExceeded("任务下一次请求将超过共享总 Tokens 上限 %d" % token_limit)
            if model == "deepseek-v4-pro":
                for key, current, extra, label in (
                    ("pro_max_calls", pro_calls, 1, "Pro 付费调用次数"),
                    ("pro_max_output_tokens", pro_output, output_tokens, "Pro 输出 Tokens"),
                    ("pro_max_total_tokens", pro_tokens, reserve_tokens, "Pro 总 Tokens"),
                ):
                    limit = int((limits or {}).get(key, 0) or 0)
                    if limit and current + extra > limit:
                        raise ModelBudgetExceeded("%s的下一次请求将超过配置上限 %d" % (label, limit))
            cursor.execute(
                """INSERT INTO model_usage_attempts
                       (request_id,attempt,task_id,stage,model,effort,budget_state,
                        reserved_cost_cny,reserved_input_tokens,reserved_output_tokens,
                        reserved_total_tokens,result_status,detail_json,created_at,updated_at)
                     VALUES (%s,%s,%s,%s,%s,%s,'reserved',%s,%s,%s,%s,'reserved','{}'::jsonb,NOW(),NOW())
                     ON CONFLICT (request_id,attempt) DO NOTHING RETURNING request_id""",
                (request_id, attempt, task_id, str(stage), str(model), str(effort), reserve_cost,
                 input_tokens, output_tokens, reserve_tokens),
            )
            if not cursor.fetchone():
                raise ModelBudgetExceeded("模型请求预留已存在，拒绝重复发送")
            self._refresh_task_totals(cursor, task_id)
            self.connection.commit()
            return {"reserved_cost_cny": str(reserve_cost), "reserved_tokens": reserve_tokens}
        except Exception:
            self.connection.rollback()
            raise

    def record_attempt(self, task_id, request_id, attempt, result_status, usage=None, detail=None):
        request_id = str(uuid.UUID(str(request_id)))
        usage = usage or {}
        prompt_tokens = _int(usage.get("prompt_tokens"))
        completion_tokens = _int(usage.get("completion_tokens"))
        total_tokens = _int(usage.get("total_tokens")) or prompt_tokens + completion_tokens
        prompt_details = usage.get("prompt_tokens_details", {}) or {}
        completion_details = usage.get("completion_tokens_details", {}) or {}
        cache_hit = _int(usage.get("prompt_cache_hit_tokens", prompt_details.get("cached_tokens", 0)))
        cache_miss = _int(usage.get("prompt_cache_miss_tokens"))
        reasoning = _int(completion_details.get("reasoning_tokens"))
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT task_id,model,budget_state FROM model_usage_attempts WHERE request_id=%s AND attempt=%s FOR UPDATE", (request_id, attempt))
            row = cursor.fetchone()
            if not row:
                # Cache hits and P1 calls not protected by this task ledger have
                # no pre-reservation; they do not spend task budget here.
                self.connection.commit()
                return False
            stored_task_id, model, state = str(row[0]), str(row[1]), str(row[2])
            if stored_task_id != str(task_id):
                raise RuntimeError("模型预留与任务编号不一致")
            has_usage = bool(prompt_tokens or completion_tokens or total_tokens)
            settlement = _settlement(result_status, detail, has_usage)
            if state == "reserved" and settlement == "settled":
                actual_cost = Decimal(str(ModelUsageLedger.estimate_peak_cost_cny(model, prompt_tokens, completion_tokens)))
                budget_state = "settled"
            elif state == "reserved" and settlement == "released":
                actual_cost, budget_state = Decimal("0"), "released"
            elif state == "reserved":
                actual_cost, budget_state = None, "unknown"
            else:
                actual_cost, budget_state = None, state
            cursor.execute(
                """UPDATE model_usage_attempts SET budget_state=%s,result_status=%s,
                       actual_cost_cny=%s,prompt_tokens=%s,completion_tokens=%s,total_tokens=%s,
                       cache_hit_tokens=%s,cache_miss_tokens=%s,reasoning_tokens=%s,
                       detail_json=%s::jsonb,updated_at=NOW()
                     WHERE request_id=%s AND attempt=%s""",
                (budget_state, str(result_status), actual_cost, prompt_tokens, completion_tokens,
                 total_tokens, cache_hit, cache_miss, reasoning,
                 json.dumps(detail or {}, ensure_ascii=False), request_id, attempt),
            )
            self._refresh_task_totals(cursor, stored_task_id)
            self.connection.commit()
            return True
        except Exception:
            self.connection.rollback()
            raise

    def record(self, task_id, stage, model, effort, attempt, result_status, usage=None, detail=None):
        """Record cache-only events, which deliberately have no model reservation."""
        if result_status not in {"cache_hit", "cache_rejected"}:
            raise ValueError("没有共享预留的模型事件不得直接记账")
        request_id = str(uuid.uuid4())
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """INSERT INTO model_usage_attempts
                       (request_id,attempt,task_id,stage,model,effort,budget_state,
                        reserved_cost_cny,actual_cost_cny,reserved_input_tokens,
                        reserved_output_tokens,reserved_total_tokens,prompt_tokens,
                        completion_tokens,total_tokens,result_status,detail_json,created_at,updated_at)
                     VALUES (%s,1,%s,%s,%s,%s,'settled',0,0,0,0,0,0,0,0,%s,%s::jsonb,NOW(),NOW())""",
                (request_id, str(task_id), str(stage), str(model), str(effort),
                 str(result_status), json.dumps(detail or {}, ensure_ascii=False)),
            )
            self._refresh_task_totals(cursor, str(task_id))
            self.connection.commit()
            return request_id
        except Exception:
            self.connection.rollback()
            raise

    @staticmethod
    def _refresh_task_totals(cursor, task_id):
        cursor.execute(
            """UPDATE research_tasks task SET
                   estimated_cost_cny=COALESCE((SELECT SUM(CASE WHEN budget_state IN ('reserved','unknown')
                                THEN reserved_cost_cny ELSE COALESCE(actual_cost_cny,0) END)
                         FROM model_usage_attempts WHERE task_id=%s),0),
                   total_tokens=COALESCE((SELECT SUM(CASE WHEN budget_state IN ('reserved','unknown')
                                THEN reserved_total_tokens ELSE total_tokens END)
                         FROM model_usage_attempts WHERE task_id=%s),0),
                   updated_at=NOW() WHERE task.task_id=%s""",
            (task_id, task_id, task_id),
        )


__all__ = ["PostgresModelUsageLedger"]
