"""Local SQLite adapter for verified-email login and one fast delivery.

This module is deliberately not connected to the public HTTP server. Production
must use PostgreSQL, a real email sender, secure cookies and shared rate limits.
"""

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


CODE_TTL = timedelta(minutes=10)
RESEND_DELAY = timedelta(seconds=60)
SESSION_TTL = timedelta(days=7)
MAX_ATTEMPTS = 5
TECHNICAL_FAILURES = frozenset({"platform_error", "model_error", "worker_timeout", "storage_error"})


def _time(now=None):
    return now or datetime.now(timezone.utc)


def _digest(secret, purpose, value):
    return hmac.new(secret, (purpose + ":" + value).encode("utf-8"), hashlib.sha256).hexdigest()


def normalize_email(email):
    if not isinstance(email, str):
        raise ValueError("邮箱格式无效")
    value = email.strip().casefold()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("邮箱格式无效")
    return value


class LocalIdentityStore:
    def __init__(self, path, secret):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("身份密钥至少需要 32 字节")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secret = secret
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS email_challenges (
                    email_hash TEXT PRIMARY KEY, challenge_id TEXT NOT NULL, code_hash TEXT NOT NULL,
                    issued_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, consumed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    email_hash TEXT PRIMARY KEY, verified_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, email_hash TEXT NOT NULL REFERENCES users(email_hash),
                    expires_at TEXT NOT NULL, revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS entitlements (
                    email_hash TEXT PRIMARY KEY REFERENCES users(email_hash),
                    state TEXT NOT NULL CHECK(state IN ('available','reserved','consumed')),
                    task_id TEXT, updated_at TEXT NOT NULL,
                    CHECK ((state = 'reserved' AND task_id IS NOT NULL) OR (state != 'reserved'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_reserved_task ON entitlements(task_id) WHERE state='reserved';
            """)

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 15000")
        return db

    def issue_code(self, email, now=None):
        """Return a one-time code to the caller, which must send it out of band."""
        instant = _time(now)
        email_hash = _digest(self.secret, "email", normalize_email(email))
        code = "%06d" % secrets.randbelow(1_000_000)
        challenge_id = secrets.token_urlsafe(16)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT issued_at FROM email_challenges WHERE email_hash=?", (email_hash,)).fetchone()
            if old and instant - datetime.fromisoformat(old["issued_at"]) < RESEND_DELAY:
                raise ValueError("请在 60 秒后重发验证码")
            db.execute("""INSERT INTO email_challenges(email_hash,challenge_id,code_hash,issued_at,expires_at,attempts,consumed_at)
                VALUES (?,?,?,?,?,0,NULL) ON CONFLICT(email_hash) DO UPDATE SET
                challenge_id=excluded.challenge_id, code_hash=excluded.code_hash, issued_at=excluded.issued_at,
                expires_at=excluded.expires_at, attempts=0, consumed_at=NULL""",
                (email_hash, challenge_id, _digest(self.secret, "code:" + email_hash, code), instant.isoformat(),
                 (instant + CODE_TTL).isoformat()))
        return code, challenge_id

    def revoke_code(self, email, challenge_id):
        """Revoke only the failed send, not a newer challenge for the same email."""
        email_hash = _digest(self.secret, "email", normalize_email(email))
        with self.connect() as db:
            db.execute("DELETE FROM email_challenges WHERE email_hash=? AND challenge_id=?",
                       (email_hash, challenge_id))

    def verify_code(self, email, code, now=None):
        instant = _time(now)
        email_hash = _digest(self.secret, "email", normalize_email(email))
        supplied = _digest(self.secret, "code:" + email_hash, str(code))
        valid = False
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM email_challenges WHERE email_hash=?", (email_hash,)).fetchone()
            if not row or row["consumed_at"] or instant >= datetime.fromisoformat(row["expires_at"]) or row["attempts"] >= MAX_ATTEMPTS:
                raise ValueError("验证码无效或已过期")
            if not hmac.compare_digest(row["code_hash"], supplied):
                db.execute("UPDATE email_challenges SET attempts=attempts+1 WHERE email_hash=?", (email_hash,))
            else:
                valid = True
                db.execute("UPDATE email_challenges SET consumed_at=? WHERE email_hash=?", (instant.isoformat(), email_hash))
                db.execute("INSERT INTO users(email_hash,verified_at) VALUES (?,?) ON CONFLICT(email_hash) DO UPDATE SET verified_at=excluded.verified_at", (email_hash, instant.isoformat()))
                db.execute("INSERT INTO entitlements(email_hash,state,updated_at) VALUES (?,'available',?) ON CONFLICT(email_hash) DO NOTHING", (email_hash, instant.isoformat()))
                token = secrets.token_urlsafe(32)
                db.execute("INSERT INTO sessions(token_hash,email_hash,expires_at) VALUES (?,?,?)",
                           (_digest(self.secret, "session", token), email_hash, (instant + SESSION_TTL).isoformat()))
        if not valid:
            raise ValueError("验证码无效或已过期")
        return token

    def session_email_hash(self, token, now=None):
        if not isinstance(token, str) or not token:
            return None
        instant = _time(now)
        with self.connect() as db:
            row = db.execute("SELECT email_hash,expires_at,revoked_at FROM sessions WHERE token_hash=?",
                             (_digest(self.secret, "session", token),)).fetchone()
        return row["email_hash"] if row and not row["revoked_at"] and instant < datetime.fromisoformat(row["expires_at"]) else None

    def revoke_session(self, token, now=None):
        with self.connect() as db:
            db.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=?",
                       (_time(now).isoformat(), _digest(self.secret, "session", token)))

    def reserve_fast(self, session_token, task_id, now=None):
        email_hash = self.session_email_hash(session_token, now)
        if not email_hash:
            raise PermissionError("请先验证邮箱")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("任务标识无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE entitlements SET state='reserved',task_id=?,updated_at=? WHERE email_hash=? AND state='available'",
                                 (task_id, _time(now).isoformat(), email_hash)).rowcount
            if not changed:
                raise ValueError("首次免费资格已使用或被其他任务预留")
        return True

    def settle_fast(self, task_id, outcome, now=None):
        if outcome not in {"completed", "partial"} | TECHNICAL_FAILURES:
            raise ValueError("资格结算原因无效")
        next_state = "available" if outcome in TECHNICAL_FAILURES else "consumed"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE entitlements SET state=?,task_id=NULL,updated_at=? WHERE task_id=? AND state='reserved'",
                                 (next_state, _time(now).isoformat(), task_id)).rowcount
            if changed != 1:
                raise ValueError("任务没有可结算的首次免费预留")
        return next_state

    def entitlement_state(self, session_token, now=None):
        email_hash = self.session_email_hash(session_token, now)
        if not email_hash:
            raise PermissionError("请先验证邮箱")
        with self.connect() as db:
            row = db.execute("SELECT state FROM entitlements WHERE email_hash=?", (email_hash,)).fetchone()
        return row["state"] if row else None
