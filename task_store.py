"""SQLite persistence for local research-delivery tasks."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self):
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    tier TEXT NOT NULL CHECK(tier IN ('fast','deep')),
                    status TEXT NOT NULL CHECK(status IN ('active','cancelled','completed','failed')),
                    current_stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, kind)
                );
            """)

    def create_task(self, topic, tier):
        task_id = "TASK-" + uuid.uuid4().hex[:12]
        now = utc_now()
        with self.connect() as connection:
            connection.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?)", (task_id, topic, tier, "active", "P1", now, now))
            connection.execute("INSERT INTO events(task_id,stage,event_type,payload_json,created_at) VALUES (?,?,?,?,?)", (task_id, "P1", "task_created", "{}", now))
        return self.get_task(task_id)

    def record_event(self, task_id, stage, event_type, payload=None, artifact_kind=None):
        now = utc_now()
        encoded = json.dumps(payload or {}, ensure_ascii=False)
        with self.connect() as connection:
            task = connection.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise KeyError("任务不存在")
            if task["status"] == "cancelled":
                raise ValueError("任务已取消，请先恢复")
            connection.execute("UPDATE tasks SET current_stage=?,updated_at=? WHERE task_id=?", (stage, now, task_id))
            connection.execute("INSERT INTO events(task_id,stage,event_type,payload_json,created_at) VALUES (?,?,?,?,?)", (task_id, stage, event_type, encoded, now))
            if artifact_kind:
                connection.execute("INSERT INTO artifacts(task_id,kind,payload_json,updated_at) VALUES (?,?,?,?) ON CONFLICT(task_id,kind) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at", (task_id, artifact_kind, encoded, now))
        return self.get_task(task_id)

    def set_status(self, task_id, status):
        if status not in ("active", "cancelled", "completed", "failed"):
            raise ValueError("任务状态无效")
        now = utc_now()
        with self.connect() as connection:
            result = connection.execute("UPDATE tasks SET status=?,updated_at=? WHERE task_id=?", (status, now, task_id))
            if result.rowcount != 1:
                raise KeyError("任务不存在")
            task = connection.execute("SELECT current_stage FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            connection.execute("INSERT INTO events(task_id,stage,event_type,payload_json,created_at) VALUES (?,?,?,?,?)", (task_id, task["current_stage"], "status_" + status, "{}", now))
        return self.get_task(task_id)

    def get_task(self, task_id):
        with self.connect() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise KeyError("任务不存在")
            events = connection.execute("SELECT stage,event_type,payload_json,created_at FROM events WHERE task_id=? ORDER BY event_id", (task_id,)).fetchall()
            artifacts = connection.execute("SELECT kind,payload_json,updated_at FROM artifacts WHERE task_id=? ORDER BY kind", (task_id,)).fetchall()
        return {
            **dict(task),
            "events": [{**dict(item), "payload": json.loads(item["payload_json"])} for item in events],
            "artifacts": {item["kind"]: {"data": json.loads(item["payload_json"]), "updated_at": item["updated_at"]} for item in artifacts},
        }

    def export_markdown(self, task_id):
        task = self.get_task(task_id)
        final = task["artifacts"].get("final_delivery", {}).get("data")
        report = (final or {}).get("final_report", {}).get("markdown")
        if not report:
            report = task["artifacts"].get("report", {}).get("data", {}).get("report_markdown")
        if not report:
            raise ValueError("任务尚无可导出的报告")
        return "# %s\n\n- 任务编号：%s\n- 版本：%s\n- 状态：%s\n\n%s\n" % (task["topic"], task_id, task["tier"], task["status"], report)
