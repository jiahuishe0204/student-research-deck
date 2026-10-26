"""Anonymous P1 control plane behind the same-origin EdgeOne gateway."""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import secrets

from model_usage import ModelBudgetExceeded
from postgres_model_usage import PostgresModelUsageLedger
from preauth_budget import DailyBudgetExceeded, PostgresPreAuthDailyBudget
from preauth_intent_ticket import issue_intent_ticket
from scf_app import build_workflow
from security_rate_limit import PREAUTH_INTENT_IP_POLICY, consume, subject_hash


ROOT = Path(__file__).resolve().parent


def _response(status, payload):
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
            "body": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}


def _gateway_allowed(event, secret):
    headers = {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}
    return bool(secret) and secrets.compare_digest(secret, headers.get("x-gateway-secret", ""))


def _source_ip(event, *, trusted_gateway):
    if trusted_gateway:
        headers = {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}
        source = headers.get("x-edgeone-client-ip", "")
    else:
        source = str((event.get("requestContext") or {}).get("sourceIp", ""))
    try:
        return str(ipaddress.ip_address(source))
    except ValueError as exc:
        raise PermissionError("请求来源无效") from exc


def _rate_limit(connection, gateway_secret, source_ip):
    digest = subject_hash(gateway_secret, "preauth-intent-ip", source_ip)
    try:
        allowed = consume(connection, dimension="preauth-intent-ip",
                          subject_digest=digest, policy=PREAUTH_INTENT_IP_POLICY)
        # Persist the denied hit too: rolling it back would erase the 30-minute block.
        connection.commit()
        return allowed
    except Exception:
        connection.rollback()
        raise


def _services(environ):  # pragma: no cover - real SCF smoke path
    import psycopg

    database_url = str(environ.get("DATABASE_URL", "")).strip()
    gateway_secret = str(environ.get("EDGEONE_GATEWAY_SECRET", ""))
    signing_secret = str(environ.get("PREAUTH_INTENT_SIGNING_SECRET", ""))
    if not database_url or len(gateway_secret) < 32 or len(signing_secret) < 32:
        raise RuntimeError("匿名题目服务缺少必要配置")
    connection = psycopg.connect(database_url)
    try:
        workflow = build_workflow(
            ROOT, environ,
            daily_budget_ledger=PostgresPreAuthDailyBudget(connection),
            usage_ledger=PostgresModelUsageLedger(connection),
        )
    except Exception:
        connection.close()
        raise

    return {"connection": connection, "workflow": workflow,
            "rate_limit": lambda source_ip: _rate_limit(connection, gateway_secret, source_ip),
            "signing_secret": signing_secret}


def main_handler(event, context=None, *, services=None):
    owned = services is None
    environ = os.environ
    if owned and not _gateway_allowed(event, environ.get("EDGEONE_GATEWAY_SECRET", "")):
        return _response(403, {"ok": False, "message": "请求来源无效"})
    if event.get("path") != "/api/intent" or str(event.get("httpMethod", "GET")).upper() != "POST":
        return _response(404, {"ok": False, "message": "接口不存在"})
    try:
        source_ip = _source_ip(event, trusted_gateway=owned)
        services = services or _services(environ)
        if not services["rate_limit"](source_ip):
            return _response(429, {"ok": False, "message": "请求过于频繁，请稍后重试"})
        raw_body = event.get("body") or "{}"
        if not isinstance(raw_body, str) or len(raw_body.encode("utf-8")) > 8192:
            raise ValueError("题目请求过大")
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError("题目格式无效")
        topic = str(payload.get("topic") or "").strip()
        tier = str(payload.get("tier") or "fast").strip()
        if hasattr(services["workflow"], "set_task_context"):
            services["workflow"].set_task_context("unassigned")
        intent, _usage = services["workflow"].create_intent(topic, tier, request_timeout=45)
        ticket = issue_intent_ticket(topic, tier, intent, services["signing_secret"])
        return _response(200, {"ok": True, "data": intent, "intent_ticket": ticket})
    except (DailyBudgetExceeded, ModelBudgetExceeded):
        return _response(429, {"ok": False, "message": "登录前题目理解额度已用完，请稍后重试"})
    except (PermissionError, ValueError, json.JSONDecodeError):
        return _response(400, {"ok": False, "message": "题目或请求来源无效"})
    except Exception:
        return _response(503, {"ok": False, "message": "题目理解服务暂时不可用"})
    finally:
        if owned and services is not None:
            services["connection"].close()


__all__ = ["main_handler"]
