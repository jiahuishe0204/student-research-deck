"""Durable per-attempt model usage accounting and configurable Pro guards."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class ModelBudgetExceeded(RuntimeError):
    pass


class ModelUsageLedger:
    PEAK_PRICES_CNY_PER_MILLION = {
        "deepseek-flash": {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0},
        "deepseek-v4-flash": {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0},
        "deepseek-v4-pro": {"cache_hit": 0.30, "cache_miss": 9.0, "output": 27.0},
    }
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS model_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, stage TEXT NOT NULL,
                model TEXT NOT NULL, effort TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0, cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                cache_miss_tokens INTEGER NOT NULL DEFAULT 0, reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            )""")

    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, task_id, stage, model, effort, attempt, status, usage=None, detail=None):
        usage = usage or {}
        prompt_details = usage.get("prompt_tokens_details", {}) or {}
        completion_details = usage.get("completion_tokens_details", {}) or {}
        values = (
            task_id, stage, model, effort, int(attempt), status,
            int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0),
            int(usage.get("total_tokens", 0) or 0),
            int(usage.get("prompt_cache_hit_tokens", prompt_details.get("cached_tokens", 0)) or 0),
            int(usage.get("prompt_cache_miss_tokens", 0) or 0),
            int(completion_details.get("reasoning_tokens", 0) or 0),
            json.dumps(detail or {}, ensure_ascii=False), datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with self.connect() as connection:
            connection.execute("INSERT INTO model_usage(task_id,stage,model,effort,attempt,status,prompt_tokens,completion_tokens,total_tokens,cache_hit_tokens,cache_miss_tokens,reasoning_tokens,detail_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)

    def summary(self, task_id):
        with self.connect() as connection:
            rows = connection.execute("SELECT model,COUNT(*) calls,SUM(CASE WHEN total_tokens>0 THEN 1 ELSE 0 END) billable_calls,SUM(completion_tokens) output_tokens,SUM(total_tokens) total_tokens,SUM(reasoning_tokens) reasoning_tokens FROM model_usage WHERE task_id=? GROUP BY model", (task_id,)).fetchall()
        return {row["model"]: dict(row) for row in rows}

    @staticmethod
    def _is_peak(instant):
        beijing = instant.astimezone(timezone(timedelta(hours=8)))
        return beijing.weekday() < 5 and (9 <= beijing.hour < 12 or 14 <= beijing.hour < 18)

    def cost_cny(self, task_id, force_peak=False):
        with self.connect() as connection:
            rows = connection.execute("SELECT model,prompt_tokens,completion_tokens,cache_hit_tokens,cache_miss_tokens,created_at FROM model_usage WHERE task_id=?", (task_id,)).fetchall()
        total = 0.0
        for row in rows:
            prices = self.PEAK_PRICES_CNY_PER_MILLION.get(row["model"])
            if not prices:
                continue
            multiplier = 1.0 if force_peak or self._is_peak(datetime.fromisoformat(row["created_at"])) else 0.5
            hit = int(row["cache_hit_tokens"] or 0)
            miss = int(row["cache_miss_tokens"] or 0)
            miss += max(0, int(row["prompt_tokens"] or 0) - hit - miss)
            total += multiplier * (hit * prices["cache_hit"] + miss * prices["cache_miss"] + int(row["completion_tokens"] or 0) * prices["output"]) / 1_000_000
        return total

    def peak_cost_cny(self, task_id):
        return self.cost_cny(task_id, force_peak=True)

    def guard(self, task_id, model, limits, next_output_tokens=0, next_input_tokens=0):
        cost_limit = float((limits or {}).get("task_max_cost_cny", 0) or 0)
        prices = self.PEAK_PRICES_CNY_PER_MILLION.get(model)
        if cost_limit and prices:
            multiplier = 1.0 if self._is_peak(datetime.now(timezone.utc)) else 0.5
            reserved_cost = multiplier * (int(next_input_tokens or 0) * prices["cache_miss"] + int(next_output_tokens or 0) * prices["output"]) / 1_000_000
            if self.cost_cny(task_id) + reserved_cost > cost_limit:
                raise ModelBudgetExceeded("任务下一次请求将超过费用上限 %.3f 元" % cost_limit)
        all_models = self.summary(task_id)
        task_total = sum(int(item.get("total_tokens", 0) or 0) for item in all_models.values())
        task_limit = int((limits or {}).get("task_max_total_tokens", 0) or 0)
        reservation = int(next_input_tokens or 0) + int(next_output_tokens or 0)
        if task_limit and task_total + reservation > task_limit:
            raise ModelBudgetExceeded("任务下一次请求将超过总 Tokens 上限 %d" % task_limit)
        if model != "deepseek-v4-pro":
            return
        summary = all_models.get(model, {})
        checks = (
            ("pro_max_calls", int(summary.get("billable_calls", 0)), 1, "Pro 付费调用次数"),
            ("pro_max_output_tokens", int(summary.get("output_tokens", 0) or 0), int(next_output_tokens or 0), "Pro 输出 Tokens"),
            ("pro_max_total_tokens", int(summary.get("total_tokens", 0) or 0), 0, "Pro 总 Tokens"),
        )
        for key, current, reservation, label in checks:
            limit = int((limits or {}).get(key, 0) or 0)
            exceeded = current + reservation > limit if reservation else current >= limit
            if limit and exceeded:
                raise ModelBudgetExceeded("%s的下一次请求将超过配置上限 %d" % (label, limit))
