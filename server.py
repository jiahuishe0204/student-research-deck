#!/usr/bin/env python3
"""Local MVP server for the research delivery prototype."""

import argparse
import http.client
import json
import os
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from contracts import ContractError, load_contract, validate_stage_output
from retrieval import search_all
from task_store import TaskStore

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
MAX_BODY_BYTES = 32 * 1024


def load_dotenv(path):
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def deepseek_json(api_key, model, system, stage_prompt, payload, effort="none", validator=None):
    thinking = "disabled" if effort == "none" else "enabled"
    base_content = stage_prompt + "\n\n实际输入JSON：\n" + json.dumps(payload, ensure_ascii=False)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    last_error = None
    for attempt in range(2):
        suffix = "" if attempt == 0 else "\n\n上一次输出未通过校验：%s。请严格按照 output_contract 修正，确保JSON完整闭合，不得输出JSON之外的文本。" % str(last_error)[:300]
        request_body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": base_content + suffix}],
            "stream": False, "max_tokens": 6000,
            "response_format": {"type": "json_object"}, "reasoning_effort": effort, "thinking": {"type": thinking},
        }
        request = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json", "User-Agent": "research-delivery-local-mvp/0.2"},
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 0:
                continue
            raise
        usage = data.get("usage", {})
        for key in total_usage:
            total_usage[key] += int(usage.get(key, 0) or 0)
        content = data["choices"][0]["message"].get("content") or ""
        if not content.strip():
            last_error = RuntimeError("模型未返回可用内容")
            continue
        try:
            parsed = json.loads(content)
            if validator:
                parsed = validator(parsed)
            total_usage["attempts"] = attempt + 1
            return parsed, total_usage
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
    raise last_error


def validate_intent(value):
    required = {
        "domain",
        "normalized_topic",
        "scope_hint",
        "tier",
        "assumptions",
        "need_clarification",
        "clarification_question",
        "confirmation_text",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("意图识别返回字段不完整")
    if not isinstance(value["need_clarification"], bool):
        raise ValueError("澄清状态无效")
    if value["need_clarification"] and not isinstance(value["clarification_question"], str):
        raise ValueError("需要澄清时必须返回一个问题")
    return value


def validate_plan(value):
    required = {
        "research_scope",
        "exclusions",
        "questions",
        "search_concepts",
        "source_plan",
        "selection_criteria",
        "stop_conditions",
        "report_outline",
        "ppt_story_arc",
        "risks",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("调研规划返回字段不完整")
    array_fields = ("exclusions", "source_plan", "selection_criteria", "stop_conditions", "report_outline", "ppt_story_arc", "risks")
    if any(not isinstance(value.get(field), list) for field in array_fields):
        raise ValueError("调研规划数组字段类型无效")
    if not isinstance(value.get("search_concepts"), dict):
        raise ValueError("检索概念必须为对象")
    if not 3 <= len(value.get("questions", [])) <= 6:
        raise ValueError("调研问题数量必须为 3—6 个")
    question_keys = {"question_id", "question", "evidence_needs"}
    if any(not isinstance(item, dict) or set(item) != question_keys or not isinstance(item["evidence_needs"], list) for item in value["questions"]):
        raise ValueError("调研问题字段结构无效")
    return value


def validate_screen(value, candidate_ids, keep_max=None):
    validate_stage_output("P3", value)
    decisions = value["decisions"]
    returned_ids = [item["source_id"] for item in decisions]
    if len(returned_ids) != len(set(returned_ids)):
        raise ContractError("P3 返回了重复 source_id")
    if set(returned_ids) != set(candidate_ids):
        raise ContractError("P3 必须且只能判断本次全部候选资料")
    counts = {status: sum(item["status"] == status for item in decisions) for status in ("keep", "reserve", "drop")}
    summary = value["summary"]
    if summary["candidate_count"] != len(candidate_ids) or any(summary[status + "_count"] != count for status, count in counts.items()):
        raise ContractError("P3 汇总数量与逐条判断不一致")
    if keep_max is not None and counts["keep"] > keep_max:
        raise ContractError("P3 保留数量超过本版本预算")
    return value


def validate_evidence(value, source_id, source_access=None):
    validate_stage_output("P4", value)
    if value["source_id"] != source_id:
        raise ContractError("P4 source_id 与输入不一致")
    if any(item["source_id"] != source_id for item in value["evidence_records"]):
        raise ContractError("P4 证据引用了其他来源")
    if any(item["source_id"] != source_id for item in value["figure_records"]):
        raise ContractError("P4 图片引用了其他来源")
    if source_access != "full_text" and value["reading_scope"] == "full_text":
        raise ContractError("P4 未获得全文时不能标记为全文阅读")
    return value


def validate_report(value, evidence_ids):
    validate_stage_output("P5", value)
    if not set(value["used_evidence_ids"]).issubset(set(evidence_ids)):
        raise ContractError("P5 使用了不存在的 evidence_id")
    return value


def validate_ppt(value, evidence_ids, figure_ids):
    validate_stage_output("P6", value)
    allowed_evidence = set(evidence_ids)
    allowed_figures = set(figure_ids)
    for page in value["pages"]:
        if not set(page["evidence_ids"]).issubset(allowed_evidence):
            raise ContractError("P6 页面使用了不存在的 evidence_id")
        for figure in page["figure_refs"]:
            if figure["figure_id"] not in allowed_figures:
                raise ContractError("P6 页面使用了不存在的 figure_id")
    return value


def validate_claims(value, evidence_ids):
    validate_stage_output("P7", value)
    claim_ids = [item["claim_id"] for item in value["claims"]]
    if len(claim_ids) != len(set(claim_ids)):
        raise ContractError("P7 claim_id 重复")
    if any(not set(item["cited_evidence_ids"]).issubset(set(evidence_ids)) for item in value["claims"]):
        raise ContractError("P7 声明使用了不存在的 evidence_id")
    return value


def validate_verification(value, claim_ids, evidence_ids):
    validate_stage_output("P8", value)
    result_ids = [item["claim_id"] for item in value["results"]]
    if set(result_ids) != set(claim_ids) or len(result_ids) != len(set(result_ids)):
        raise ContractError("P8 必须且只能核验本次全部声明")
    if any(not set(item["valid_evidence_ids"]).issubset(set(evidence_ids)) for item in value["results"]):
        raise ContractError("P8 使用了不存在的 evidence_id")
    for item in value["results"]:
        if item["support_status"] == "unsupported" and item["action"] != "remove":
            raise ContractError("P8 不支持的声明必须删除")
        if item["support_status"] == "partially_supported" and item["action"] != "revise":
            raise ContractError("P8 部分支持的声明必须降级修订")
    return value


def validate_final(value, claim_ids, source_ids, evidence_ids):
    validate_stage_output("P9", value)
    if not set(value["source_ids"]).issubset(set(source_ids)) or not set(value["evidence_ids"]).issubset(set(evidence_ids)):
        raise ContractError("P9 输出引用了输入之外的来源或证据")
    if not set(value["final_report"]["used_evidence_ids"]).issubset(set(evidence_ids)):
        raise ContractError("P9 报告使用了不存在的 evidence_id")
    if any(not set(page["evidence_ids"]).issubset(set(evidence_ids)) for page in value["final_ppt"]["pages"]):
        raise ContractError("P9 PPT 使用了不存在的 evidence_id")
    if any(item["claim_id"] not in set(claim_ids) for item in value["change_log"]):
        raise ContractError("P9 变更记录使用了不存在的 claim_id")
    return value


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "ResearchDeliveryMVP/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

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
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/api/health":
            self.send_json(
                HTTPStatus.OK,
                {"ok": True, "deepseek_configured": bool(self.server.api_key)},
            )
            return
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "tasks"]:
            task_id = parts[2]
            try:
                if len(parts) == 3:
                    self.send_json(HTTPStatus.OK, {"data": self.server.task_store.get_task(task_id)})
                    return
                if len(parts) == 4 and parts[3] == "export.md":
                    markdown = self.server.task_store.export_markdown(task_id)
                    self.send_text(HTTPStatus.OK, markdown, "text/markdown; charset=utf-8", 'attachment; filename="%s.md"' % task_id)
                    return
            except KeyError as exc:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                return
            except ValueError as exc:
                self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
        super().do_GET()

    def do_POST(self):
        try:
            body = self.read_json()
            parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")
            if self.path == "/api/tasks":
                topic = str(body.get("topic", "")).strip()
                tier = body.get("tier", "fast")
                if not 2 <= len(topic) <= 500 or tier not in ("fast", "deep"):
                    raise ValueError("任务主题或版本无效")
                self.send_json(HTTPStatus.CREATED, {"data": self.server.task_store.create_task(topic, tier)})
                return
            if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                task_id, action = parts[2], parts[3]
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
            if self.path != "/api/search" and not self.server.api_key:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "未配置 DeepSeek API 密钥"})
                return
            if self.path == "/api/intent":
                topic = str(body.get("topic", "")).strip()
                tier = body.get("tier", "fast")
                if not 2 <= len(topic) <= 500 or tier not in ("fast", "deep"):
                    raise ValueError("请输入 2—500 字的主题并选择有效版本")
                output, usage = deepseek_json(
                    self.server.api_key,
                    "deepseek-flash",
                    self.server.system_prompt,
                    self.server.intent_prompt,
                    {"topic": topic, "tier": tier, "runtime_config": {"language": "zh-CN"}},
                    "none",
                )
                self.send_json(HTTPStatus.OK, {"data": validate_intent(output), "usage": usage})
                return
            if self.path == "/api/plan":
                topic = str(body.get("topic", "")).strip()
                clarification = str(body.get("clarification", "")).strip()
                tier = body.get("tier", "fast")
                if not 2 <= len(topic) <= 500 or tier not in ("fast", "deep"):
                    raise ValueError("规划输入无效")
                normalized = topic + (("；用户澄清：" + clarification) if clarification else "")
                model = "deepseek-v4-pro" if tier == "deep" else "deepseek-flash"
                effort = "high"
                output, usage = deepseek_json(
                    self.server.api_key,
                    model,
                    self.server.system_prompt,
                    self.server.plan_prompt,
                    {
                        "intent": {"domain": "life_science", "normalized_topic": normalized, "tier": tier, "need_clarification": False},
                        "tier": tier,
                        "available_sources": ["PubMed", "Europe PMC", "Crossref", "official"],
                        "runtime_config": {"source_limit": 19 if tier == "deep" else 10, "language": "zh-CN"},
                    },
                    effort,
                )
                self.send_json(HTTPStatus.OK, {"data": validate_plan(output), "usage": usage})
                return
            if self.path == "/api/search":
                topic = str(body.get("topic", "")).strip()
                query = str(body.get("query", "")).strip() or topic
                if not 2 <= len(topic) <= 500 or not 2 <= len(query) <= 1000:
                    raise ValueError("检索主题或检索式无效")
                output = search_all(query, per_source=4)
                output["topic"] = topic
                self.send_json(HTTPStatus.OK, {"data": output})
                return
            if self.path == "/api/screen":
                topic = str(body.get("topic", "")).strip()
                tier = body.get("tier", "fast")
                plan = body.get("plan")
                candidates = body.get("candidates")
                if not 2 <= len(topic) <= 500 or tier not in ("fast", "deep") or not isinstance(plan, dict):
                    raise ValueError("筛选主题或规划无效")
                if not isinstance(candidates, list) or not 1 <= len(candidates) <= 30:
                    raise ValueError("候选资料数量必须为 1—30 条")
                candidate_ids = [str(item.get("source_id", "")).strip() for item in candidates if isinstance(item, dict)]
                if len(candidate_ids) != len(candidates) or any(not item for item in candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
                    raise ValueError("候选资料 source_id 缺失或重复")
                keep_max = 8 if tier == "deep" else 4
                compact_candidates = [{key: item.get(key) for key in ("source_id", "source", "title", "abstract", "year", "access", "url")} for item in candidates]
                output, usage = deepseek_json(
                    self.server.api_key, "deepseek-flash", self.server.system_prompt, self.server.screen_prompt,
                    {"topic": topic, "plan": plan, "candidate_sources": compact_candidates, "limits": {"keep_max": keep_max, "tier": tier}, "output_contract": load_contract("P3")},
                    "none", lambda value: validate_screen(value, candidate_ids, keep_max),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if self.path == "/api/evidence":
                source_record = body.get("source_record")
                question_ids = body.get("question_ids", [])
                if not isinstance(source_record, dict) or not isinstance(question_ids, list):
                    raise ValueError("证据提取输入无效")
                source_id = str(source_record.get("source_id", "")).strip()
                source_text = str(source_record.get("abstract", "")).strip()
                if not source_id:
                    raise ValueError("来源缺少 source_id")
                if not source_text:
                    output = {
                        "evidence_version": "1.0", "source_id": source_id,
                        "extraction_status": "no_extractable_evidence", "reading_scope": "metadata_only",
                        "evidence_records": [], "figure_records": [], "no_extractable_reason": "当前来源没有可读取摘要或正文",
                    }
                    self.send_json(HTTPStatus.OK, {"data": validate_evidence(output, source_id, source_record.get("access")), "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}})
                    return
                compact_record = {key: source_record.get(key) for key in ("source_id", "source", "title", "authors", "journal", "year", "url", "access")}
                output, usage = deepseek_json(
                    self.server.api_key, "deepseek-flash", self.server.system_prompt, self.server.evidence_prompt,
                    {"source_record": compact_record, "source_text": source_text, "question_ids": question_ids, "output_contract": load_contract("P4")},
                    "none", lambda value: validate_evidence(value, source_id, source_record.get("access")),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if self.path == "/api/report":
                intent = body.get("intent")
                plan = body.get("plan")
                evidence_records = body.get("evidence_records")
                tier = body.get("tier", "fast")
                if not isinstance(intent, dict) or not isinstance(plan, dict) or not isinstance(evidence_records, list) or tier not in ("fast", "deep"):
                    raise ValueError("报告生成输入无效")
                if not 1 <= len(evidence_records) <= 100:
                    raise ValueError("至少需要 1 条且最多处理 100 条证据")
                evidence_ids = [str(item.get("evidence_id", "")).strip() for item in evidence_records if isinstance(item, dict)]
                if len(evidence_ids) != len(evidence_records) or any(not item for item in evidence_ids) or len(set(evidence_ids)) != len(evidence_ids):
                    raise ValueError("证据编号缺失或重复")
                output, usage = deepseek_json(
                    self.server.api_key, "deepseek-flash", self.server.system_prompt, self.server.report_prompt,
                    {"intent": intent, "plan": plan, "evidence_records": evidence_records, "tier": tier, "output_contract": load_contract("P5")},
                    "none", lambda value: validate_report(value, evidence_ids),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if self.path == "/api/ppt":
                intent = body.get("intent")
                report = body.get("report")
                evidence_records = body.get("evidence_records")
                figure_records = body.get("figure_records", [])
                constraints = body.get("constraints", {})
                if not isinstance(intent, dict) or not isinstance(report, dict) or not isinstance(evidence_records, list) or not isinstance(figure_records, list) or not isinstance(constraints, dict):
                    raise ValueError("PPT 内容包输入无效")
                evidence_ids = [str(item.get("evidence_id", "")).strip() for item in evidence_records if isinstance(item, dict)]
                figure_ids = [str(item.get("figure_id", "")).strip() for item in figure_records if isinstance(item, dict)]
                if len(evidence_ids) != len(evidence_records) or any(not item for item in evidence_ids):
                    raise ValueError("PPT 输入包含无效证据编号")
                if len(figure_ids) != len(figure_records) or any(not item for item in figure_ids):
                    raise ValueError("PPT 输入包含无效图片编号")
                output, usage = deepseek_json(
                    self.server.api_key, "deepseek-flash", self.server.system_prompt, self.server.ppt_prompt,
                    {"intent": intent, "report": report, "evidence_records": evidence_records, "figure_records": figure_records, "constraints": constraints, "output_contract": load_contract("P6")},
                    "none", lambda value: validate_ppt(value, evidence_ids, figure_ids),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if self.path == "/api/claims":
                report = body.get("report")
                ppt = body.get("ppt")
                evidence_ids = body.get("evidence_ids")
                if not isinstance(report, dict) or not isinstance(ppt, dict) or not isinstance(evidence_ids, list):
                    raise ValueError("声明拆分输入无效")
                output, usage = deepseek_json(
                    self.server.api_key, "deepseek-flash", self.server.system_prompt, self.server.claims_prompt,
                    {"report": report, "ppt_package": ppt, "evidence_ids": evidence_ids, "output_contract": load_contract("P7")},
                    "none", lambda value: validate_claims(value, evidence_ids),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            if self.path == "/api/verify":
                claims = body.get("claims")
                evidence_records = body.get("evidence_records")
                source_records = body.get("source_records")
                tier = body.get("tier", "fast")
                if not isinstance(claims, dict) or not isinstance(evidence_records, list) or not isinstance(source_records, list) or tier not in ("fast", "deep"):
                    raise ValueError("独立核验输入无效")
                claim_ids = [item.get("claim_id") for item in claims.get("claims", []) if isinstance(item, dict)]
                evidence_ids = [item.get("evidence_id") for item in evidence_records if isinstance(item, dict)]
                high_risk = any(item.get("risk_level") == "high" for item in claims.get("claims", []) if isinstance(item, dict))
                model = "deepseek-v4-pro" if tier == "deep" or high_risk else "deepseek-flash"
                effort = "high" if model == "deepseek-v4-pro" else "none"
                output, usage = deepseek_json(
                    self.server.api_key, model, self.server.system_prompt, self.server.verify_prompt,
                    {"claims": claims, "evidence_records": evidence_records, "source_records": source_records, "output_contract": load_contract("P8")},
                    effort, lambda value: validate_verification(value, claim_ids, evidence_ids),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage, "route": {"model": model, "reason": "high_risk_or_deep" if model == "deepseek-v4-pro" else "standard_claims"}})
                return
            if self.path == "/api/final":
                verification = body.get("verification_results")
                report = body.get("draft_report")
                ppt = body.get("draft_ppt")
                claim_ids = body.get("claim_ids")
                source_ids = body.get("source_ids")
                evidence_ids = body.get("evidence_ids")
                evidence_version = str(body.get("evidence_version", "1.0"))
                if not all(isinstance(item, list) for item in (claim_ids, source_ids, evidence_ids)) or not all(isinstance(item, dict) for item in (verification, report, ppt)):
                    raise ValueError("最终装配输入无效")
                output, usage = deepseek_json(
                    self.server.api_key, "deepseek-flash", self.server.system_prompt, self.server.final_prompt,
                    {"verification_results": verification, "draft_report": report, "draft_ppt": ppt, "claim_ids": claim_ids, "source_ids": source_ids, "evidence_ids": evidence_ids, "evidence_version": evidence_version, "output_contract": load_contract("P9")},
                    "none", lambda value: validate_final(value, claim_ids, source_ids, evidence_ids),
                )
                self.send_json(HTTPStatus.OK, {"data": output, "usage": usage})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except KeyError as exc:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
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
    server.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "").strip()
    server.system_prompt = (ROOT / "prompts/system.md").read_text(encoding="utf-8")
    server.intent_prompt = (ROOT / "prompts/P1-intent.md").read_text(encoding="utf-8")
    server.plan_prompt = (ROOT / "prompts/P2-plan.md").read_text(encoding="utf-8")
    server.screen_prompt = (ROOT / "prompts/P3-screen.md").read_text(encoding="utf-8")
    server.evidence_prompt = (ROOT / "prompts/P4-evidence.md").read_text(encoding="utf-8")
    server.report_prompt = (ROOT / "prompts/P5-report.md").read_text(encoding="utf-8")
    server.ppt_prompt = (ROOT / "prompts/P6-ppt.md").read_text(encoding="utf-8")
    server.claims_prompt = (ROOT / "prompts/P7-claims.md").read_text(encoding="utf-8")
    server.verify_prompt = (ROOT / "prompts/P8-verify.md").read_text(encoding="utf-8")
    server.final_prompt = (ROOT / "prompts/P9-final.md").read_text(encoding="utf-8")
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
