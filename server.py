#!/usr/bin/env python3
"""Local MVP server for the research delivery prototype."""

import argparse
import http.client
import json
import os
import traceback
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from retrieval import search_all

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


def deepseek_json(api_key, model, system, stage_prompt, payload, effort="none"):
    thinking = "disabled" if effort == "none" else "enabled"
    base_content = stage_prompt + "\n\n实际输入JSON：\n" + json.dumps(payload, ensure_ascii=False)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    last_error = None
    for attempt in range(2):
        suffix = "" if attempt == 0 else "\n\n上一次输出未形成完整JSON。请压缩描述，确保JSON完整闭合，不得输出JSON之外的文本。"
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
            total_usage["attempts"] = attempt + 1
            return parsed, total_usage
        except json.JSONDecodeError as exc:
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
        super().do_GET()

    def do_POST(self):
        try:
            if not self.server.api_key:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "未配置 DeepSeek API 密钥"})
                return
            body = self.read_json()
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
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
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
    server.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "").strip()
    server.system_prompt = (ROOT / "prompts/system.md").read_text(encoding="utf-8")
    server.intent_prompt = (ROOT / "prompts/P1-intent.md").read_text(encoding="utf-8")
    server.plan_prompt = (ROOT / "prompts/P2-plan.md").read_text(encoding="utf-8")
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
