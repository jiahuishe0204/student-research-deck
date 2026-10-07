"""DeepSeek-compatible JSON client with validation-aware retries."""

import http.client
import json
import os
import urllib.error
import urllib.request


def deepseek_json(api_key, model, system, stage_prompt, payload, effort="none", validator=None, max_tokens=6000, max_attempts=2, request_timeout=300):
    thinking = "disabled" if effort == "none" else "enabled"
    base_content = stage_prompt + "\n\n实际输入JSON：\n" + json.dumps(payload, ensure_ascii=False)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    last_error = None
    for attempt in range(max_attempts):
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
                data = json.loads(response.read().decode("utf-8"))
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
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
