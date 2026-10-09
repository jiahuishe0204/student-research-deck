#!/usr/bin/env python3
"""Local MVP server for the research delivery prototype."""

import argparse
import json
import os
import traceback
import urllib.error
import urllib.parse
import threading
import time
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from epo_ops import EPOClient
from model_routing import ModelRouter
from model_usage import ModelUsageLedger
from retrieval import search_all
from task_store import TaskStore
from workflow_validation import (
    validate_claims,
    validate_evidence,
    validate_final,
    validate_intent,
    validate_plan,
    validate_ppt,
    validate_report,
    validate_screen,
    validate_verification,
)
from workflow_service import WorkflowService

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
MAX_BODY_BYTES = 512 * 1024


class RateLimiter:
    def __init__(self, limit=30, window_seconds=60, clock=time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.events = defaultdict(deque)
        self.lock = threading.Lock()
        self.next_cleanup = 0

    def allow(self, key):
        now = self.clock()
        with self.lock:
            if now >= self.next_cleanup:
                for known_key, known_bucket in list(self.events.items()):
                    while known_bucket and known_bucket[0] <= now - self.window_seconds:
                        known_bucket.popleft()
                    if not known_bucket:
                        del self.events[known_key]
                self.next_cleanup = now + self.window_seconds
            bucket = self.events[key]
            while bucket and bucket[0] <= now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


def load_dotenv(path):
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "ResearchDeliveryMVP/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def request_path(self):
        return urllib.parse.urlparse(self.path).path

    def send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, status, value, content_type="text/plain; charset=utf-8", disposition=None):
        body = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("请求长度无效")
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("请求内容为空或过大")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("请求必须使用 UTF-8 编码") from exc
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return value

    def require_task_access(self, task_id=None):
        task_id = task_id or self.headers.get("X-Task-ID", "").strip()
        token = self.headers.get("X-Task-Token", "").strip()
        if not task_id or not self.server.task_store.authorize(task_id, token):
            raise PermissionError("任务访问凭据无效")
        return task_id

    def do_GET(self):
        path = self.request_path()
        if path == "/api/health":
            self.send_json(
                HTTPStatus.OK,
                {"ok": True, "deepseek_configured": bool(self.server.api_key),
                 "epo_ops_configured": self.server.epo_client is not None},
            )
            return
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "tasks"]:
            task_id = parts[2]
            try:
                self.require_task_access(task_id)
                if len(parts) == 3:
                    self.send_json(HTTPStatus.OK, {"data": self.server.task_store.get_task(task_id)})
                    return
                if len(parts) == 4 and parts[3] == "export.md":
                    markdown = self.server.task_store.export_markdown(task_id)
                    self.send_text(HTTPStatus.OK, markdown, "text/markdown; charset=utf-8", 'attachment; filename="%s.md"' % task_id)
                    return
                if len(parts) == 4 and parts[3] == "usage":
                    self.send_json(HTTPStatus.OK, {"data": self.server.model_usage.summary(task_id)})
                    return
            except KeyError as exc:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            except PermissionError as exc:
                self.send_json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
                return
            except ValueError as exc:
                self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
        super().do_GET()

    def do_POST(self):
        try:
            body = self.read_json()
            path = self.request_path()
            parts = path.strip("/").split("/")
            if path == "/api/tasks":
                if not self.server.rate_limiter.allow("create:" + self.client_address[0]):
                    self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "请求过于频繁，请稍后再试"})
                    return
                topic = str(body.get("topic", "")).strip()
                tier = body.get("tier", "fast")
                if not 2 <= len(topic) <= 500 or tier not in ("fast", "deep"):
                    raise ValueError("任务主题或版本无效")
                self.send_json(HTTPStatus.CREATED, {"data": self.server.task_store.create_task(topic, tier)})
                return
            if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                task_id, action = parts[2], parts[3]
                self.require_task_access(task_id)
                if action == "events":
                    stage = str(body.get("stage", "")).strip()
                    event_type = str(body.get("event_type", "")).strip()
                    payload = body.get("payload", {})
                    artifact_kind = body.get("artifact_kind")
                    if not stage or not event_type or not isinstance(payload, dict):
                        raise ValueError("任务事件无效")
                    self.send_json(HTTPStatus.OK, {"data": self.server.task_store.record_event(task_id, stage, event_type, payload, artifact_kind)})
                    return
                if action in ("cancel", "resume", "complete"):
                    status = {"cancel": "cancelled", "resume": "active", "complete": "completed"}[action]
                    self.send_json(HTTPStatus.OK, {"data": self.server.task_store.set_status(task_id, status)})
                    return
            if path != "/api/search" and not self.server.api_key:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "未配置 DeepSeek API 密钥"})
                return
            task_id = self.require_task_access()
            self.server.workflow.set_task_context(task_id)
            if not self.server.rate_limiter.allow("work:" + self.client_address[0] + ":" + task_id):
                self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "任务调用过于频繁，请稍后再试"})
                return
            if path == "/api/intent":
                output, usage = self.server.workflow.create_intent(body.get("topic"), body.get("tier", "fast"))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/plan":
                output, usage = self.server.workflow.create_plan(body.get("topic"), body.get("clarification"), body.get("tier", "fast"), body.get("intent"))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/search":
                topic = str(body.get("topic", "")).strip()
                query = str(body.get("query", "")).strip() or topic
                epo_query = str(body.get("epo_query", "")).strip() or query
                if not 2 <= len(topic) <= 500 or not 2 <= len(query) <= 1000 or len(epo_query) > 500:
                    raise ValueError("检索主题或检索式无效")
                output = search_all(query, per_source=4, epo_client=self.server.epo_client, epo_query=epo_query)
                output["topic"] = topic
                self.send_json(HTTPStatus.OK, {"data": output})
                return
            if path == "/api/screen":
                output, usage = self.server.workflow.screen_sources(body.get("topic"), body.get("plan"), body.get("candidates"), body.get("tier", "fast"))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/evidence":
                output, usage = self.server.workflow.extract_evidence(body.get("source_record"), body.get("question_ids", []), body.get("tier", "fast"))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/report":
                output, usage = self.server.workflow.create_report(body.get("intent"), body.get("plan"), body.get("evidence_records"), body.get("tier", "fast"))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/ppt":
                output, usage = self.server.workflow.create_ppt(
                    body.get("intent"), body.get("report"), body.get("evidence_records"),
                    body.get("figure_records", []), body.get("constraints", {}), body.get("tier", "fast"), body.get("plan"),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/claims":
                report = body.get("report")
                ppt = body.get("ppt")
                evidence_ids = body.get("evidence_ids")
                tier = body.get("tier", "fast")
                if not isinstance(report, dict) or not isinstance(ppt, dict) or not isinstance(evidence_ids, list) or tier not in ("fast", "deep"):
                    raise ValueError("声明拆分输入无效")
                output, usage, metadata = self.server.workflow.extract_claims(report, ppt, evidence_ids, tier)
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage, **metadata})
                return
            if path == "/api/verify":
                claims = body.get("claims")
                evidence_records = body.get("evidence_records")
                source_records = body.get("source_records")
                tier = body.get("tier", "fast")
                if not isinstance(claims, dict) or not isinstance(evidence_records, list) or not isinstance(source_records, list) or tier not in ("fast", "deep"):
                    raise ValueError("独立核验输入无效")
                output, usage, metadata = self.server.workflow.verify_claims(claims, evidence_records, source_records, tier)
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage, "route": metadata})
                return
            if path == "/api/final":
                if isinstance(body.get("claims"), list):
                    output, usage = self.server.workflow.assemble_final_deterministic(
                        body.get("verification_results"), body.get("draft_report"), body.get("draft_ppt"),
                        body.get("claims"), body.get("source_ids"), body.get("evidence_ids"), body.get("evidence_version", "1.0"),
                    )
                else:
                    output, usage = self.server.workflow.assemble_final(
                        body.get("verification_results"), body.get("draft_report"), body.get("draft_ppt"),
                        body.get("claim_ids"), body.get("source_ids"), body.get("evidence_ids"),
                        body.get("evidence_version", "1.0"), body.get("tier", "fast"),
                    )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except KeyError as exc:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except PermissionError as exc:
            self.send_json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except urllib.error.HTTPError as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": "DeepSeek 请求失败", "status": exc.code})
        except Exception:
            traceback.print_exc()
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "生成失败，请稍后重试"})

    def log_message(self, format, *args):
        print("[%s] %s" % (self.log_date_time_string(), format % args))


def create_server(host="127.0.0.1", port=4180, api_key=None):
    load_dotenv(ROOT.parent / ".env")
    server = ThreadingHTTPServer((host, port), AppHandler)
    server.task_store = TaskStore(ROOT / "data" / "tasks.sqlite3")
    server.rate_limiter = RateLimiter()
    server.model_router = ModelRouter.from_file()
    server.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "").strip()
    server.epo_client = EPOClient.from_environment(ROOT / "data" / "private" / "epo-usage.sqlite3")
    server.model_usage = ModelUsageLedger(ROOT / "data" / "private" / "model-usage.sqlite3")
    server.workflow = WorkflowService.from_project(server.api_key, server.model_router, ROOT, usage_ledger=server.model_usage, model_limits={
        "task_max_cost_cny": float(os.environ.get("MODEL_TASK_MAX_COST_CNY", "0") or 0),
        "task_max_total_tokens": int(os.environ.get("MODEL_TASK_MAX_TOTAL_TOKENS", "0") or 0),
        "pro_max_calls": int(os.environ.get("MODEL_PRO_MAX_CALLS", "0") or 0),
        "pro_max_output_tokens": int(os.environ.get("MODEL_PRO_MAX_OUTPUT_TOKENS", "0") or 0),
        "pro_max_total_tokens": int(os.environ.get("MODEL_PRO_MAX_TOTAL_TOKENS", "0") or 0),
    })
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4180)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print("Research Delivery MVP: http://%s:%s" % (args.host, args.port))
    print("DeepSeek configured:", "yes" if server.api_key else "no")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
