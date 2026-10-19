"""SCF HTTP control plane for OTP sessions and private downloads."""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from functools import partial

from delivery_repository import PostgresDeliveryRepository
from identity_vault import IdentityVault
from otp_service import OtpService
from private_delivery_api import authenticated_download
from production_config import load_production_config
from production_session import COOKIE_ATTRIBUTES
from production_session import SessionAuthenticator
from tencent_delivery import TencentCosArtifactStore


SESSION_COOKIE = "research_session"


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


def _services():  # pragma: no cover - real SCF smoke path
    import psycopg
    config = load_production_config()
    connection = psycopg.connect(config.database_url)
    repository = PostgresDeliveryRepository(connection, config.public_origin)
    vault = IdentityVault(config.identity_secret, repository)
    auth = SessionAuthenticator(connection, config.identity_secret)
    store = TencentCosArtifactStore.from_config(config)
    return {"connection": connection, "otp": OtpService(connection, repository, vault, config.identity_secret),
            "auth": auth, "download": partial(authenticated_download, auth, repository, store)}


def main_handler(event, context=None, *, services=None):
    owned = services is None
    services = services or _services()
    method = str(event.get("httpMethod", "GET")).upper()
    path = str(event.get("path", ""))
    payload = _body(event)
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    try:
        if method == "POST" and path.endswith("/auth/otp/request"):
            # Trust only SCF's connection metadata, never client-supplied X-Forwarded-For.
            source_ip = str((event.get("requestContext") or {}).get("sourceIp", ""))
            if not source_ip:
                raise PermissionError("请求来源无效")
            services["otp"].issue(payload.get("email", ""), source_ip)
            return _response(202, {"ok": True, "message": "若地址有效，验证码将很快送达"})
        if method == "POST" and path.endswith("/auth/otp/verify"):
            result = services["otp"].verify(payload.get("challenge_id", ""), payload.get("code", ""))
            cookie = "%s=%s; %s; Max-Age=604800" % (SESSION_COOKIE, result["session_token"], COOKIE_ATTRIBUTES)
            return _response(200, {"ok": True, "csrf_token": result["csrf_token"]}, {"Set-Cookie": cookie})
        if method == "POST" and path.endswith("/auth/logout"):
            services["auth"].revoke(_session_cookie(event))
            return _response(200, {"ok": True}, {"Set-Cookie": "%s=; %s; Max-Age=0" % (SESSION_COOKIE, COOKIE_ATTRIBUTES)})
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
