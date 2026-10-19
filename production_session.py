"""Server-side PostgreSQL session authentication and CSRF enforcement."""

from __future__ import annotations

import hmac
from security_rate_limit import subject_hash


COOKIE_ATTRIBUTES = "Path=/; Secure; HttpOnly; SameSite=Strict"


class SessionAuthenticator:
    def __init__(self, connection, secret):
        self.connection = connection
        self.secret = secret

    def authenticate(self, session_token, *, csrf_token=None, require_csrf=False):
        if not session_token:
            raise PermissionError("登录状态无效")
        session_digest = subject_hash(self.secret, "session", session_token)
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT user_id,csrf_hash FROM user_sessions
                 WHERE session_hash=%s AND revoked_at IS NULL AND expires_at>CURRENT_TIMESTAMP
                   AND last_active_at>CURRENT_TIMESTAMP-INTERVAL '24 hours'
                 FOR UPDATE""", (session_digest,))
        row = cursor.fetchone()
        if not row:
            self.connection.rollback()
            raise PermissionError("登录状态无效")
        if require_csrf:
            submitted = subject_hash(self.secret, "csrf", csrf_token or "")
            if not hmac.compare_digest(str(row[1]), submitted):
                self.connection.rollback()
                raise PermissionError("请求校验失败")
        cursor.execute("UPDATE user_sessions SET last_active_at=CURRENT_TIMESTAMP WHERE session_hash=%s",
                       (session_digest,))
        self.connection.commit()
        return str(row[0])

    def revoke(self, session_token):
        cursor = self.connection.cursor()
        cursor.execute("UPDATE user_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE session_hash=%s",
                       (subject_hash(self.secret, "session", session_token),))
        self.connection.commit()


__all__ = ["COOKIE_ATTRIBUTES", "SessionAuthenticator"]
