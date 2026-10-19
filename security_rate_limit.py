"""Atomic PostgreSQL-backed abuse limits shared by all server instances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac


@dataclass(frozen=True)
class RatePolicy:
    window_seconds: int
    max_requests: int
    block_seconds: int


OTP_POLICY = RatePolicy(window_seconds=600, max_requests=5, block_seconds=1800)
OTP_IP_POLICY = RatePolicy(window_seconds=600, max_requests=20, block_seconds=1800)
OTP_GLOBAL_POLICY = RatePolicy(window_seconds=600, max_requests=2000, block_seconds=600)


def subject_hash(secret, dimension, subject):
    return hmac.new(str(secret).encode(), (dimension + ":" + str(subject)).encode(), hashlib.sha256).hexdigest()


def consume(connection, *, dimension, subject_digest, policy=OTP_POLICY, now=None):
    """Consume one slot using one row lock; return False while blocked/over limit."""
    instant = now or datetime.now(timezone.utc)
    window_start = instant - timedelta(seconds=policy.window_seconds)
    blocked_until = instant + timedelta(seconds=policy.block_seconds)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO security_rate_limits
                (dimension, subject_hash, window_started_at, request_count)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (dimension, subject_hash) DO UPDATE SET
                window_started_at = CASE
                    WHEN security_rate_limits.window_started_at < %s THEN EXCLUDED.window_started_at
                    ELSE security_rate_limits.window_started_at END,
                request_count = CASE
                    WHEN security_rate_limits.window_started_at < %s THEN 1
                    ELSE security_rate_limits.request_count + 1 END,
                blocked_until = CASE
                    WHEN security_rate_limits.blocked_until > %s THEN security_rate_limits.blocked_until
                    WHEN (CASE WHEN security_rate_limits.window_started_at < %s THEN 1
                               ELSE security_rate_limits.request_count + 1 END) > %s THEN %s
                    ELSE NULL END
            RETURNING request_count, blocked_until
            """,
            (dimension, subject_digest, instant, window_start, window_start,
             instant, window_start, policy.max_requests, blocked_until),
        )
        count, blocked = cursor.fetchone()
    return count <= policy.max_requests and not (blocked and blocked > instant)


def consume_many(connection, subjects, *, policy=OTP_POLICY, now=None):
    """Atomically consume all dimensions or persist none of them."""
    try:
        allowed = all(consume(connection, dimension=item[0], subject_digest=item[1],
                              policy=item[2] if len(item) > 2 else policy, now=now)
                      for item in subjects)
        if allowed:
            connection.commit()
        else:
            connection.rollback()
        return allowed
    except Exception:
        connection.rollback()
        raise


__all__ = ["OTP_POLICY", "OTP_IP_POLICY", "OTP_GLOBAL_POLICY", "RatePolicy", "consume",
           "consume_many", "subject_hash"]
