"""SCF HTTP control plane for OTP sessions and private downloads."""

from __future__ import annotations

import json
import os
import secrets
from http.cookies import SimpleCookie
from functools import partial

from delivery_repository import PostgresDeliveryRepository
from identity_vault import IdentityVault
from otp_service import OtpService
from private_delivery_api import authenticated_download
from production_config import load_cos_config, load_delivery_common_config
from production_task_queue import PostgresTaskQueue
from production_session import COOKIE_ATTRIBUTES
from production_session import SessionAuthenticator
from tencent_delivery import TencentCosArtifactStore


SESSION_COOKIE = "research_session"


def _gateway_allowed(event):
    expected = os.environ.get("EDGEONE_GATEWAY_SECRET", "")
    headers = {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}
    supplied = headers.get("x-gateway-secret", "")
    return bool(expected) and secrets.compare_digest(expected, supplied)


def _response(status, body, headers=None):
    return {"statusCode": status, "headers": {"Content-Type": "application/json", **(headers or {})},
            "body": json.dumps(body, ensure_ascii=False, separators=(",", ":"))}


def _body(event):
    try:
        value = json.loads(event.get("body") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _session_cookie(event):
    cookie = SimpleCookie(); cookie.load((event.get("headers") or {}).get("cookie", ""))
    return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else ""


def _services(path):  # pragma: no cover - real SCF smoke path
    import psycopg
    common = load_delivery_common_config()
    connection = psycopg.connect(common.database_url)
    repository = PostgresDeliveryRepository(connection, common.public_origin)
    vault = IdentityVault(common.identity_secret, repository)
    auth = SessionAuthenticator(connection, common.identity_secret)
    services = {"connection": connection, "auth": auth}
    if path.rstrip("/").endswith("/tasks") or "/tasks/" in path:
        services["tasks"] = PostgresTaskQueue(connection)
    if "/auth/otp/" in path:
        services["otp"] = OtpService(connection, repository, vault, common.identity_secret)
    if path.endswith("/delivery/download"):
        store = TencentCosArtifactStore.from_config(load_cos_config())
        services["download"] = partial(authenticated_download, auth, repository, store)
    return services


def main_handler(event, context=None, *, services=None):
    path = str(event.get("path", ""))
    owned = services is None
    if owned and not _gateway_allowed(event):
        return _response(403, {"ok": False, "message": "请求来源无效"}, {"Cache-Control": "no-store"})
    services = services or _services(path)
    method = str(event.get("httpMethod", "GET")).upper()
    payload = _body(event)
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    try:
        if method == "GET" and path.rstrip("/").endswith("/health"):
            cursor = services["connection"].cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return _response(200, {"ok": True, "database": "ok", "worker": "configured"},
                             {"Cache-Control": "no-store"})
        if method == "POST" and path.endswith("/auth/otp/request"):
            # Trust only SCF's connection metadata, never client-supplied X-Forwarded-For.
            source_ip = (headers.get("x-edgeone-client-ip", "") if owned else
                         str((event.get("requestContext") or {}).get("sourceIp", "")))
            if not source_ip:
                raise PermissionError("请求来源无效")
            challenge_id = services["otp"].issue(payload.get("email", ""), source_ip)
            return _response(202, {"ok": True, "challenge_id": challenge_id,
                                   "message": "若地址有效，验证码将很快送达"})
        if method == "POST" and path.endswith("/auth/otp/verify"):
            result = services["otp"].verify(payload.get("challenge_id", ""), payload.get("code", ""))
            cookie = "%s=%s; %s; Max-Age=604800" % (SESSION_COOKIE, result["session_token"], COOKIE_ATTRIBUTES)
            return _response(200, {"ok": True, "csrf_token": result["csrf_token"]}, {"Set-Cookie": cookie})
        if method == "POST" and path.endswith("/auth/logout"):
            services["auth"].authenticate(_session_cookie(event), csrf_token=headers.get("x-csrf-token", ""),
                                          require_csrf=True)
            services["auth"].revoke(_session_cookie(event))
            return _response(200, {"ok": True}, {"Set-Cookie": "%s=; %s; Max-Age=0" % (SESSION_COOKIE, COOKIE_ATTRIBUTES)})
        if method == "POST" and path.rstrip("/").endswith("/tasks"):
            user_id = services["auth"].authenticate(
                _session_cookie(event), csrf_token=headers.get("x-csrf-token", ""), require_csrf=True,
            )
            task = services["tasks"].create_task(
                user_id=user_id, topic=payload.get("topic", ""), tier=payload.get("tier", "fast"),
            )
            return _response(201, {"ok": True, "data": task}, {"Cache-Control": "no-store"})
        parts = path.strip("/").split("/")
        if method == "POST" and len(parts) >= 3 and parts[-1] == "continue" and parts[-3] == "tasks":
            user_id = services["auth"].authenticate(
                _session_cookie(event), csrf_token=headers.get("x-csrf-token", ""), require_csrf=True,
            )
            task = services["tasks"].continue_after_intent(
                user_id=user_id, task_id=parts[-2], clarification=payload.get("clarification", ""),
            )
            return _response(202, {"ok": True, "data": task}, {"Cache-Control": "no-store"})
        if method == "GET" and len(parts) >= 3 and parts[-1] == "progress" and parts[-3] == "tasks":
            user_id = services["auth"].authenticate(_session_cookie(event))
            progress = services["tasks"].task_progress(user_id=user_id, task_id=parts[-2])
            return _response(200, {"ok": True, "data": progress}, {"Cache-Control": "no-store"})
        if method == "GET" and len(parts) >= 3 and parts[-1] == "delivery" and parts[-3] == "tasks":
            user_id = services["auth"].authenticate(_session_cookie(event))
            delivery = services["tasks"].task_delivery(user_id=user_id, task_id=parts[-2])
            return _response(200, {"ok": True, "data": delivery}, {"Cache-Control": "no-store"})
        if method == "POST" and path.endswith("/delivery/download"):
            url = services["download"](
                session_token=_session_cookie(event), csrf_token=headers.get("x-csrf-token", ""),
                task_id=payload.get("task_id", ""), artifact_id=payload.get("artifact_id", ""),
                filename=payload.get("filename", "delivery"),
            )
            return _response(200, {"ok": True, "download_url": url}, {"Cache-Control": "no-store"})
        return _response(404, {"ok": False, "message": "接口不存在"})
    except (ValueError, LookupError, PermissionError):
        # Authentication and challenge failures deliberately share one response.
        return _response(401, {"ok": False, "message": "请求无效或已过期"}, {"Cache-Control": "no-store"})
    finally:
        if owned:
            services["connection"].close()


__all__ = ["SESSION_COOKIE", "main_handler"]
