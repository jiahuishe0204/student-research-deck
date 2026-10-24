"""Read-only Patsnap MCP patent adapter for the China Open Platform."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MCP_URL = "https://connect.zhihuiya.com/1458a4/mcp"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"


class PatsnapMCPError(RuntimeError):
    """Base error for Patsnap MCP transport and tool failures."""


class PatsnapMCPAuthError(PatsnapMCPError):
    pass


class PatsnapMCPQuotaError(PatsnapMCPError):
    pass


class PatsnapMCPRateLimitError(PatsnapMCPError):
    pass


def _first_json(body):
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        raise PatsnapMCPError("智慧芽 MCP 返回空响应")
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            value = line[5:].strip()
            if value and value != "[DONE]":
                return json.loads(value)
    raise PatsnapMCPError("智慧芽 MCP 返回格式无法识别")


def _tool_payload(result):
    if not isinstance(result, dict):
        return result
    for key in ("structuredContent", "structured_content"):
        if result.get(key) is not None:
            return result[key]
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("json") is not None:
            return item["json"]
        if isinstance(item.get("text"), str):
            try:
                return json.loads(item["text"])
            except json.JSONDecodeError:
                pass
    return result


def _find_results(value):
    if isinstance(value, dict):
        if isinstance(value.get("results"), list):
            return value["results"]
        for key in ("data", "result", "output"):
            found = _find_results(value.get(key))
            if found is not None:
                return found
    return None


def _date_year(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:4] if len(digits) >= 4 else ""


class PatsnapMCPClient:
    """Minimal MCP client implementing the existing patent search contract."""

    provider_name = "智慧芽 MCP"

    def __init__(self, api_key, url=DEFAULT_MCP_URL, timeout=30, opener=None):
        self.api_key = str(api_key or "").strip()
        self.url = str(url or "").strip().rstrip("/")
        self.timeout = int(timeout)
        self.opener = opener or urllib.request.urlopen
        self.session_id = ""
        self._initialized = False
        if not self.api_key:
            raise ValueError("智慧芽 MCP API Key 不能为空")
        if self.url != DEFAULT_MCP_URL:
            raise ValueError("智慧芽 MCP 地址必须使用已核验的中国区全球核心专利库")

    @classmethod
    def from_environment(cls):
        key = os.environ.get("PATSNAP_MCP_API_KEY", "").strip()
        if not key:
            return None
        return cls(key, os.environ.get("PATSNAP_MCP_URL", DEFAULT_MCP_URL),
                   int(os.environ.get("PATSNAP_MCP_TIMEOUT_SECONDS", "30") or 30))

    def _send(self, payload, allow_empty=False):
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "mcp-protocol-version": DEFAULT_PROTOCOL_VERSION,
            "User-Agent": "research-delivery-patsnap-mcp/1.0",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers,
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                response_headers = getattr(response, "headers", {})
                session_id = response_headers.get("Mcp-Session-Id", "") if response_headers else ""
                if session_id:
                    self.session_id = session_id
                body = response.read()
                if allow_empty and not body.strip():
                    return {}
                message = _first_json(body)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise PatsnapMCPAuthError("智慧芽 MCP 鉴权或权限不足") from exc
            if exc.code == 429:
                raise PatsnapMCPRateLimitError("智慧芽 MCP 调用频率超限") from exc
            raise PatsnapMCPError("智慧芽 MCP HTTP %d" % exc.code) from exc
        if message.get("error"):
            text = json.dumps(message["error"], ensure_ascii=False)
            if any(code in text for code in ("67200005", "67200007")):
                raise PatsnapMCPQuotaError("智慧芽 MCP 积分或调用额度不足")
            if any(code in text for code in ("67200000", "67200001", "67200002")):
                raise PatsnapMCPRateLimitError("智慧芽 MCP 调用频率超限")
            if any(code in text for code in ("67200003", "67200004", "67200008", "67200009")):
                raise PatsnapMCPAuthError("智慧芽 MCP 鉴权或权限不足")
            raise PatsnapMCPError("智慧芽 MCP 工具调用失败")
        return message

    def _ensure_initialized(self):
        if self._initialized:
            return
        message = self._send({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": DEFAULT_PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "research-delivery", "version": "1.0"}},
        })
        negotiated = str(message.get("result", {}).get("protocolVersion") or "")
        if negotiated and negotiated != DEFAULT_PROTOCOL_VERSION:
            raise PatsnapMCPError("智慧芽 MCP 协议版本不兼容")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"}, allow_empty=True)
        self._initialized = True

    def _call(self, method, params=None, request_id=1):
        self._ensure_initialized()
        message = self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        return message.get("result", {})

    def list_tools(self):
        return self._call("tools/list").get("tools", [])

    def search(self, query, limit=3):
        terms = list(dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", str(query))))[:6]
        if not terms:
            raise ValueError("智慧芽专利检索需要英文关键词")
        arguments = {
            "query_text": "TACD: (" + " OR ".join('\"%s\"' % term for term in terms) + ")",
            "limit": min(max(int(limit), 1), 3), "offset": 0, "stemming": 1,
            "collapse_type": "DOCDB", "collapse_by": "SCORE",
            "sort_field": "SCORE", "sort_order": "desc",
        }
        result = self._call("tools/call", {"name": "search_patents", "arguments": arguments})
        if result.get("isError") is True:
            raise PatsnapMCPError("智慧芽 MCP 专利检索工具返回错误")
        records = _find_results(_tool_payload(result))
        if records is None:
            raise PatsnapMCPError("智慧芽 MCP 专利检索缺少 results")
        normalized = []
        for item in records[:arguments["limit"]]:
            if not isinstance(item, dict):
                continue
            patent_id = str(item.get("patent_id") or "").strip()
            number = str(item.get("pn") or item.get("patent_number") or "").strip().upper()
            if not patent_id and not number:
                continue
            identifier = number or patent_id
            locator = patent_id or number
            normalized.append({
                "source": self.provider_name, "source_id": "PATSNAP:PATENT:" + identifier,
                "source_type": "patent", "patent_id": patent_id or identifier,
                "patent_number": number, "pmid": "", "doi": "",
                "title": str(item.get("title") or "Untitled patent").strip(), "abstract": "",
                "authors": [part.strip() for part in str(item.get("inventor") or "").split("|") if part.strip()][:6],
                "journal": "", "year": _date_year(item.get("pbdt") or item.get("apdt")),
                "publication_date": str(item.get("pbdt") or ""), "application_date": str(item.get("apdt") or ""),
                "assignee": str(item.get("current_assignee") or item.get("original_assignee") or "").strip(),
                "authority": str(item.get("authority") or "").strip(),
                "url": "https://analytics.zhihuiya.com/patent-view/%s" % urllib.parse.quote(locator, safe=""),
                "access": "patent_bibliographic_metadata", "reading_scope": "metadata_only",
                "retrieval_provider": "patsnap_mcp_cn",
            })
        return normalized
