"""Execute one delivery outbox event without leaking recipient data."""

from __future__ import annotations

from delivery_outbox import backoff_seconds, claim_event, classify_provider_failure, finish_event


TEMPLATE_FIELDS = {
    "send_otp": frozenset({"challenge_id", "minutes"}),
    "send_completed": frozenset({"task_label", "site_url"}),
    "send_expiry": frozenset({"task_label", "site_url", "expiry_date"}),
}
MAIL_KIND = {"send_otp": "otp", "send_completed": "completed", "send_expiry": "expiry"}


def validate_event_payload(event_type, payload):
    if event_type not in TEMPLATE_FIELDS or not isinstance(payload, dict):
        raise ValueError("邮件事件类型或载荷无效")
    extra = set(payload) - TEMPLATE_FIELDS[event_type]
    missing = TEMPLATE_FIELDS[event_type] - set(payload)
    if extra or missing:
        raise ValueError("邮件模板变量不符合白名单")
    values = {key: str(value) for key, value in payload.items()}
    if any(len(value) > 300 for value in values.values()):
        raise ValueError("邮件模板变量过长")
    if any("q-sign-" in value or "cos." in value for value in values.values()):
        raise ValueError("邮件不得包含 COS 签名地址")
    return values


def execute_one(connection, identity_vault, mailer, *, lease_seconds=120):
    event = claim_event(connection, lease_seconds=lease_seconds,
                        event_types=tuple(TEMPLATE_FIELDS))
    if not event:
        return {"status": "idle"}
    event_id, token = event["event_id"], event["lease_token"]
    try:
        variables = validate_event_payload(event["event_type"], event["payload"])
        # Recipient resolution is late-bound from encrypted identity storage;
        # neither outbox payload nor logs need the plaintext address.
        if event["event_type"] == "send_otp":
            material = identity_vault.otp_material_for_challenge(variables.pop("challenge_id"))
            recipient, variables["code"] = material["recipient"], material["code"]
        else:
            recipient = identity_vault.recipient_for_user(event["user_id"])
        response = mailer.send_template(MAIL_KIND[event["event_type"]], recipient, variables)
    except Exception as exc:
        ambiguous = bool(getattr(exc, "ambiguous_delivery", False))
        status = classify_provider_failure(
            http_status=getattr(exc, "http_status", None),
            error_code=getattr(exc, "error_code", type(exc).__name__),
            ambiguous=ambiguous,
        )
        if status == "retryable_failed" and event["attempt_count"] >= 8:
            status = "permanent_failed"
        delay = backoff_seconds(event["attempt_count"]) if status == "retryable_failed" else None
        finish_event(connection, event_id, token, status,
                     error_code=str(getattr(exc, "error_code", type(exc).__name__))[:80],
                     retry_delay_seconds=delay)
        return {"status": status, "event_id": event_id}
    if not finish_event(connection, event_id, token, "succeeded",
                        provider_request_id=response.get("request_id")):
        raise RuntimeError("邮件事件租约已失效，拒绝旧 Worker 提交状态")
    if event["event_type"] == "send_expiry":
        cursor = connection.cursor()
        cursor.execute("""UPDATE task_artifacts SET reminder_sent_at=CURRENT_TIMESTAMP
                           WHERE task_id=%s AND reminder_sent_at IS NULL""", (event["task_id"],))
        connection.commit()
    return {"status": "succeeded", "event_id": event_id,
            "provider_request_id": response.get("request_id")}


__all__ = ["TEMPLATE_FIELDS", "execute_one", "validate_event_payload"]
