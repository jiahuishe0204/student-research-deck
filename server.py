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
from model_usage import ModelBudgetExceeded, ModelUsageLedger
from retrieval import hydrate_europe_pmc_full_text, search_all, search_patsnap_literature
from research_sources import (
    assess_evidence_quality, assess_source_quality, enrich_kept_open_full_text, merge_search_results,
    plan_patsnap_queries, plan_search_queries,
)
from task_store import TaskStore
from task_public_view import delivery_view, progress_view
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


def resolve_plan_request(task, body):
    """Enforce the user's scope choice before any paid P2 call, across clients."""
    if body.get("topic") != task.get("topic") or body.get("tier", "fast") != task.get("tier"):
        raise ValueError("规划主题或版本与当前任务不一致")
    saved = task.get("artifacts", {}).get("intent", {}).get("data")
    if saved is None:
        raise ValueError("请先完成并保存题目理解，再生成规划")
    intent = validate_intent(saved)
    breadth = intent["topic_breadth"]
    choice = str(body.get("direction_id") or "").strip()
    clarification = str(body.get("clarification") or "").strip()
    if breadth == "broad":
        selected = next((item for item in intent["direction_options"] if item["direction_id"] == choice), None)
        if selected is None:
            raise ValueError("宽泛主题必须由用户选择一个研究方向，不能自动代选")
        clarification = selected["title"] + "：" + selected["focus"]
    elif choice:
        raise ValueError("当前主题没有可选研究方向")
    elif intent["need_clarification"] and not clarification:
        raise ValueError("请先回答题目澄清问题")
    return task["topic"], task["tier"], clarification, intent


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
                if len(parts) == 4 and parts[3] == "progress":
                    self.send_json(HTTPStatus.OK, {"data": progress_view(self.server.task_store.get_task(task_id))})
                    return
                if len(parts) == 4 and parts[3] == "delivery":
                    self.send_json(HTTPStatus.OK, {"data": delivery_view(self.server.task_store.get_task(task_id))})
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
                topic, tier, clarification, intent = resolve_plan_request(self.server.task_store.get_task(task_id), body)
                output, usage = self.server.workflow.create_plan(topic, clarification, tier, intent)
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/search":
                topic = str(body.get("topic", "")).strip()
                query = str(body.get("query", "")).strip() or topic
                epo_query = str(body.get("epo_query", "")).strip() or query
                tier = body.get("tier", "fast")
                if not 2 <= len(topic) <= 500 or not 2 <= len(query) <= 1000 or len(epo_query) > 500:
                    raise ValueError("检索主题或检索式无效")
                if tier not in ("fast", "deep"):
                    raise ValueError("检索版本无效")
                plan = body.get("plan")
                if plan is not None and not isinstance(plan, dict):
                    raise ValueError("检索规划无效")
                if plan:
                    queries = plan_search_queries(plan, topic)
                    results = [search_all(item, per_source=4 if tier == "deep" else 3,
                                          epo_client=self.server.epo_client if index == 0 else None,
                                          epo_query=epo_query, include_patsnap=False) for index, item in enumerate(queries)]
                    if os.environ.get("PATSNAP_API_KEY", "").strip():
                        # Keep paid retrieval bounded: at most two simple queries, two papers each.
                        patsnap_detail_cache = {}
                        for patsnap_query in plan_patsnap_queries(plan, topic):
                            try:
                                results.append({"query": "Patsnap: " + patsnap_query,
                                                "records": search_patsnap_literature(patsnap_query, 2, detail_cache=patsnap_detail_cache), "errors": []})
                            except Exception as exc:
                                results.append({"query": "Patsnap: " + patsnap_query, "records": [],
                                                "errors": [{"source": "Patsnap", "error": type(exc).__name__}]})
                    output = merge_search_results(results, 24 if tier == "deep" else 12)
                else:
                    output = search_all(query, per_source=6 if tier == "deep" else 4, epo_client=self.server.epo_client, epo_query=epo_query)
                output["topic"] = topic
                self.send_json(HTTPStatus.OK, {"data": output})
                return
            if path == "/api/screen":
                topic, plan, tier = body.get("topic"), body.get("plan"), body.get("tier", "fast")
                candidates = body.get("candidates")
                output, usage = self.server.workflow.screen_sources(topic, plan, candidates, tier)
                candidates, enrichment = enrich_kept_open_full_text(candidates, output) if tier == "deep" else (candidates, {"lookups": 0, "enriched_source_ids": [], "errors": []})
                quality = assess_source_quality(plan, candidates, output, tier)
                search_update = None
                if tier == "deep" and not quality["passed"] and body.get("supplement", True):
                    previous_queries = set(body.get("queries") or [])
                    extra_queries = [item for item in plan_search_queries(plan, topic, supplement=True, limit=3)
                                     if item not in previous_queries][:2]
                    if extra_queries:
                        extra_results = [search_all(item, per_source=4, include_patsnap=False) for item in extra_queries]
                        if os.environ.get("PATSNAP_API_KEY", "").strip():
                            for patsnap_query in plan_patsnap_queries(plan, topic, supplement=True, limit=1):
                                try:
                                    extra_results.append({"query": "Patsnap: " + patsnap_query,
                                                          "records": search_patsnap_literature(patsnap_query, 1), "errors": []})
                                except Exception as exc:
                                    extra_results.append({"query": "Patsnap: " + patsnap_query, "records": [],
                                                          "errors": [{"source": "Patsnap", "error": type(exc).__name__}]})
                        search_update = merge_search_results([{"query": "previous", "records": candidates, "errors": []}] + extra_results, 30)
                        updated = search_update["records"]
                        if {item["source_id"] for item in updated} != {item["source_id"] for item in candidates}:
                            candidates = updated
                            output, additional_usage = self.server.workflow.screen_sources(topic, plan, candidates, tier)
                            candidates, additional_enrichment = enrich_kept_open_full_text(candidates, output)
                            enrichment["lookups"] += additional_enrichment["lookups"]
                            enrichment["publisher_lookups"] = enrichment.get("publisher_lookups", 0) + additional_enrichment.get("publisher_lookups", 0)
                            enrichment["enriched_source_ids"].extend(additional_enrichment["enriched_source_ids"])
                            enrichment["errors"].extend(additional_enrichment["errors"])
                            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "attempts"):
                                usage[key] = usage.get(key, 0) + additional_usage.get(key, 0)
                            quality = assess_source_quality(plan, candidates, output, tier)
                output["quality_gate"] = quality
                output["full_text_enrichment"] = enrichment
                if search_update:
                    search_update["topic"] = topic
                    search_update["records"] = candidates
                    self.server.task_store.record_event(task_id, "P2", "supplemental_search_completed", search_update, "sources")
                else:
                    self.server.task_store.record_event(task_id, "P2", "source_search_completed", {"topic": topic, "records": candidates, "query": "planned", "errors": []}, "sources")
                self.server.task_store.record_event(task_id, "P3", "screening_and_quality_checked", output, "screening")
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage, "sources": candidates})
                return
            if path == "/api/reassess-sources":
                artifacts = self.server.task_store.get_task(task_id)["artifacts"]
                plan = artifacts.get("plan", {}).get("data", {})
                saved_sources = artifacts.get("sources", {}).get("data", {})
                screening = artifacts.get("screening", {}).get("data", {})
                if not plan or not saved_sources.get("records") or not screening.get("decisions"):
                    raise ValueError("当前任务没有可重评的规划、来源和筛选结果")
                candidates, enrichment = enrich_kept_open_full_text(saved_sources["records"], screening)
                quality = assess_source_quality(plan, candidates, screening, "deep")
                screening["quality_gate"] = quality
                screening["full_text_enrichment"] = enrichment
                saved_sources["records"] = candidates
                self.server.task_store.record_event(task_id, "P2", "source_full_text_reassessed", saved_sources, "sources")
                self.server.task_store.record_event(task_id, "P3", "source_gate_reassessed", screening, "screening")
                self.send_json(HTTPStatus.OK, {"data": screening, "sources": candidates})
                return
            if path == "/api/evidence":
                source_record = body.get("source_record") or {}
                if body.get("tier", "fast") == "deep":
                    artifacts = self.server.task_store.get_task(task_id)["artifacts"]
                    saved_plan = artifacts.get("plan", {}).get("data", {})
                    saved_sources = artifacts.get("sources", {}).get("data", {}).get("records", [])
                    saved_screening = artifacts.get("screening", {}).get("data", {})
                    gate = assess_source_quality(saved_plan, saved_sources, saved_screening, "deep")
                    if not gate["passed"]:
                        raise ValueError("来源质量门禁未通过，不能继续付费提取证据：" + "；".join(gate["problems"]))
                    kept_ids = {item.get("source_id") for item in saved_screening.get("decisions", []) if item.get("status") == "keep"}
                    if source_record.get("source_id") not in kept_ids:
                        raise ValueError("该来源未通过本任务筛选，不能提取证据")
                    source_record = next(item for item in saved_sources if item.get("source_id") == source_record["source_id"])
                source_record = hydrate_europe_pmc_full_text(source_record)
                output, usage = self.server.workflow.extract_evidence(source_record, body.get("question_ids", []), body.get("tier", "fast"))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/report":
                tier = body.get("tier", "fast")
                if tier == "deep":
                    task = self.server.task_store.get_task(task_id)
                    artifacts = task["artifacts"]
                    sources = artifacts.get("sources", {}).get("data", {}).get("records", [])
                    screening = artifacts.get("screening", {}).get("data", {})
                    saved_plan = artifacts.get("plan", {}).get("data", {})
                    if not saved_plan or saved_plan != body.get("plan"):
                        raise ValueError("报告规划与本任务保存的规划不一致")
                    gate = assess_source_quality(saved_plan, sources, screening, tier)
                    if not gate["passed"]:
                        raise ValueError("来源质量门禁未通过：" + "；".join(gate["problems"]))
                    evidence_gate = assess_evidence_quality(saved_plan, body.get("evidence_records") or [], tier)
                    if not evidence_gate["passed"]:
                        raise ValueError("证据覆盖门禁未通过：" + "；".join(evidence_gate["problems"]))
                output, usage = self.server.workflow.create_report(body.get("intent"), body.get("plan"), body.get("evidence_records"), body.get("tier", "fast"), body.get("evidence_contexts", []), body.get("figure_records", []))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if path == "/api/ppt":
                output, usage = self.server.workflow.create_ppt(
                    body.get("intent"), body.get("report"), body.get("evidence_records"),
                    body.get("figure_records", []), body.get("constraints", {}), body.get("tier", "fast"), body.get("plan"),
                    body.get("source_records", []),
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
                output, usage, metadata = self.server.workflow.verify_claims(claims, evidence_records, source_records, tier, body.get("pro_claim_ids"))
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage, "route": metadata})
                return
            if path == "/api/final":
                if not isinstance(body.get("claims"), list):
                    raise ValueError("终稿需要声明清单；不能退回到额外付费的整稿重写路径")
                artifacts = self.server.task_store.get_task(task_id)["artifacts"]
                source_records = artifacts.get("sources", {}).get("data", {}).get("records", [])
                evidence_groups = artifacts.get("evidence", {}).get("data", {}).get("groups", [])
                evidence_records = [item for group in evidence_groups for item in group.get("evidence_records", [])]
                figure_records = [item for group in evidence_groups for item in group.get("figure_records", [])]
                if not source_records or not evidence_records:
                    raise ValueError("终稿缺少已保存的来源与证据，不能生成可核验引用")
                output, usage = self.server.workflow.assemble_final_deterministic(
                    body.get("verification_results"), body.get("draft_report"), body.get("draft_ppt"),
                    body.get("claims"), body.get("source_ids"), body.get("evidence_ids"), body.get("evidence_version", "1.0"),
                    evidence_records, source_records, figure_records,
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
        except ModelBudgetExceeded as exc:
            self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "任务预算已停止", "detail": str(exc)})
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
