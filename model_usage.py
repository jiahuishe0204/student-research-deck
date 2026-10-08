"""Durable per-attempt model usage accounting and configurable Pro guards."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class ModelBudgetExceeded(RuntimeError):
    pass


class ModelUsageLedger:
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
            rows = connection.execute("SELECT model,COUNT(*) calls,SUM(completion_tokens) output_tokens,SUM(total_tokens) total_tokens,SUM(reasoning_tokens) reasoning_tokens FROM model_usage WHERE task_id=? GROUP BY model", (task_id,)).fetchall()
        return {row["model"]: dict(row) for row in rows}

    def guard(self, task_id, model, limits, next_output_tokens=0, next_input_tokens=0):
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
            ("pro_max_calls", int(summary.get("calls", 0)), 1, "Pro 调用次数"),
            ("pro_max_output_tokens", int(summary.get("output_tokens", 0) or 0), int(next_output_tokens or 0), "Pro 输出 Tokens"),
            ("pro_max_total_tokens", int(summary.get("total_tokens", 0) or 0), 0, "Pro 总 Tokens"),
        )
        for key, current, reservation, label in checks:
            limit = int((limits or {}).get(key, 0) or 0)
            exceeded = current + reservation > limit if reservation else current >= limit
            if limit and exceeded:
                raise ModelBudgetExceeded("%s的下一次请求将超过配置上限 %d" % (label, limit))
