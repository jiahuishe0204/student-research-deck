"""DeepSeek-compatible JSON client with validation-aware retries."""

import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request


def read_with_deadline(response, timeout_seconds):
    """Read chunked responses with a total wall-clock deadline, not an idle-only timeout."""
    deadline = time.monotonic() + max(1, float(timeout_seconds))
    chunks = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("模型响应超过单次总时间上限")
        try:
            sock = response.fp.raw._sock
            sock.settimeout(min(15.0, remaining))
        except AttributeError:
            pass
        chunk = response.read(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def parse_json_object(content):
    """Repair harmless JSON wrappers locally without inventing truncated content."""
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in ("```", "```json"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    return value


def deepseek_json(api_key, model, system, stage_prompt, payload, effort="none", validator=None, max_tokens=6000, max_attempts=2, request_timeout=300, usage_callback=None, before_attempt=None):
    thinking = "disabled" if effort == "none" else "enabled"
    base_content = stage_prompt + "\n\n实际输入JSON：\n" + json.dumps(payload, ensure_ascii=False)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    last_error = None
    for attempt in range(max_attempts):
        if before_attempt:
            before_attempt(attempt + 1)
        suffix = "" if attempt == 0 else "\n\n上一次输出未通过校验：%s。请严格按照 output_contract 修正，确保JSON完整闭合，不得输出JSON之外的文本。" % str(last_error)[:300]
        request_body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": base_content + suffix}],
            "stream": False,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "reasoning_effort": effort,
            "thinking": {"type": thinking},
        }
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json", "User-Agent": "research-delivery-local-mvp/0.2"},
        )
        try:
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                data = json.loads(read_with_deadline(response, request_timeout).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if usage_callback:
                usage_callback(attempt + 1, "http_error", {}, {"status": exc.code})
            if 400 <= exc.code < 500:
                raise
            last_error = exc
            if attempt + 1 < max_attempts:
                continue
            raise
        except (
            http.client.IncompleteRead, http.client.RemoteDisconnected,
            urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError,
            json.JSONDecodeError,
        ) as exc:
            if usage_callback:
                usage_callback(attempt + 1, "transport_error", {}, {"error": type(exc).__name__})
            last_error = exc
            if attempt + 1 < max_attempts:
                continue
            raise
        usage = data.get("usage", {})
        for key in total_usage:
            total_usage[key] += int(usage.get(key, 0) or 0)
        content = data["choices"][0]["message"].get("content") or ""
        if not content.strip():
            last_error = RuntimeError("模型未返回可用内容")
            if usage_callback:
                usage_callback(attempt + 1, "empty_output", usage, {})
            continue
        try:
            parsed = parse_json_object(content)
            if validator:
                parsed = validator(parsed)
            if usage_callback:
                usage_callback(attempt + 1, "accepted", usage, {})
            total_usage["attempts"] = attempt + 1
            return parsed, total_usage
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if usage_callback:
                usage_callback(attempt + 1, "rejected", usage, {"error": str(exc)[:300]})
    raise last_error
