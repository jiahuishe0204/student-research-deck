"""Short-lived proof that an anonymous P1 result came from the server."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from workflow_validation import validate_intent


MAX_TICKET_AGE_SECONDS = 3600


def _secret(value):
    secret = str(value or "")
    if len(secret) < 32:
        raise RuntimeError("匿名题目凭证密钥未配置")
    return secret.encode("utf-8")


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def issue_intent_ticket(topic, tier, intent, secret, *, now=None):
    topic = str(topic or "").strip()
    if not 2 <= len(topic) <= 500 or tier not in {"fast", "deep"}:
        raise ValueError("题目或版本无效")
    checked = validate_intent(intent)
    if checked["tier"] != tier:
        raise ValueError("题目结果与请求版本不一致")
    issued_at = int(time.time() if now is None else now)
    payload = json.dumps({"v": 1, "topic": topic, "tier": tier, "intent": checked,
                          "issued_at": issued_at}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = _encode(payload)
    signature = _encode(hmac.new(_secret(secret), b"preauth-intent-v1:" + encoded.encode("ascii"),
                                 hashlib.sha256).digest())
    return encoded + "." + signature


def verify_intent_ticket(ticket, secret, *, now=None):
    if not isinstance(ticket, str) or not 0 < len(ticket) <= 32768:
        raise ValueError("题目确认凭证无效")
    try:
        encoded, supplied = ticket.split(".", 1)
        expected = _encode(hmac.new(_secret(secret), b"preauth-intent-v1:" + encoded.encode("ascii"),
                                    hashlib.sha256).digest())
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("题目确认凭证无效")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        instant = int(time.time() if now is None else now)
        issued_at = payload["issued_at"]
        if (payload.get("v") != 1 or not isinstance(issued_at, int)
                or not 0 <= instant - issued_at <= MAX_TICKET_AGE_SECONDS):
            raise ValueError("题目确认凭证已过期")
        topic, tier = payload["topic"], payload["tier"]
        if not isinstance(topic, str) or not 2 <= len(topic) <= 500 or tier not in {"fast", "deep"}:
            raise ValueError("题目确认凭证无效")
        intent = validate_intent(payload["intent"])
        if intent["tier"] != tier:
            raise ValueError("题目确认凭证无效")
        return {"topic": topic, "tier": tier, "intent": intent}
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise ValueError("题目确认凭证无效") from exc


__all__ = ["MAX_TICKET_AGE_SECONDS", "issue_intent_ticket", "verify_intent_ticket"]
