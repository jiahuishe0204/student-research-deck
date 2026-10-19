"""Production OTP issuance without plaintext recipient or code in the outbox."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid

from identity_vault import normalize_email
from security_rate_limit import OTP_GLOBAL_POLICY, OTP_IP_POLICY, OTP_POLICY, consume_many, subject_hash


def _code_hash(secret, challenge_id, code):
    return hmac.new(str(secret).encode(), (str(challenge_id) + ":" + code).encode(), hashlib.sha256).hexdigest()


class OtpService:
    def __init__(self, connection, repository, vault, secret, clock=None):
        self.connection = connection
        self.repository = repository
        self.vault = vault
        self.secret = secret
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(self, email, source_ip):
        normalized = normalize_email(email)
        email_digest = self.vault.email_hash(normalized)
        dimensions = [
            ("ip", subject_hash(self.secret, "ip", source_ip), OTP_IP_POLICY),
            ("email", subject_hash(self.secret, "email", email_digest), OTP_POLICY),
            ("ip_email", subject_hash(self.secret, "ip_email", source_ip + ":" + email_digest), OTP_POLICY),
            ("global", subject_hash(self.secret, "global", "otp"), OTP_GLOBAL_POLICY),
        ]
        if not consume_many(self.connection, dimensions, now=self.clock()):
            raise PermissionError("请求过于频繁，请稍后再试")
        challenge_id = str(uuid.uuid4())
        code = "%06d" % secrets.randbelow(1_000_000)
        issued_at = self.clock()
        self.repository.create_otp_challenge_and_event(
            challenge_id=challenge_id, email_hash=email_digest,
            email_ciphertext=self.vault.encrypt_challenge_value(challenge_id, normalized, "email"),
            code_hash=_code_hash(self.secret, challenge_id, code),
            code_ciphertext=self.vault.encrypt_challenge_value(challenge_id, code, "code"),
            issued_at=issued_at, expires_at=issued_at + timedelta(minutes=10),
            event_id=str(uuid.uuid4()), idempotency_key="otp:" + challenge_id,
        )
        return challenge_id

    def verify(self, challenge_id, code):
        if not str(code).isdigit() or len(str(code)) != 6:
            raise ValueError("验证码无效或已过期")
        material = self.vault.otp_material_for_challenge(challenge_id)
        email = normalize_email(material["recipient"])
        email_digest = self.vault.email_hash(email)
        user_id = self.repository.user_id_for_email_hash(email_digest) or str(uuid.uuid4())
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = self.clock()
        actual_user_id = self.repository.verify_challenge_and_open_session(
            challenge_id=str(challenge_id), submitted_hash=_code_hash(self.secret, challenge_id, str(code)),
            email_hash=email_digest, user_id=user_id,
            user_email_ciphertext=self.vault.encrypt(user_id, email),
            session_hash=subject_hash(self.secret, "session", session_token),
            csrf_hash=subject_hash(self.secret, "csrf", csrf_token),
            now=now, session_expires_at=now + timedelta(days=7),
        )
        if not actual_user_id:
            raise ValueError("验证码无效或已过期")
        return {"user_id": str(actual_user_id), "session_token": session_token, "csrf_token": csrf_token}


__all__ = ["OtpService"]
