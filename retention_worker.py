"""Schedule expiry reminders and enforce the seven-day COS retention policy."""

from __future__ import annotations

from datetime import datetime, timezone


def run_retention_cycle(repository, lifecycle, *, now=None, limit=100):
    instant = now or datetime.now(timezone.utc)
    reminders_due = 0
    expired = 0
    failures = []
    expired_challenges_cleared = repository.purge_expired_challenge_secrets(now=instant)

    # The repository must insert the reminder event and set reminder_sent_at in
    # one transaction. Its unique idempotency key makes concurrent scans safe.
    for artifact_id in repository.enqueue_due_expiry_reminders(now=instant, limit=limit):
        reminders_due += 1

    for claim in repository.claim_due_expirations(now=instant, limit=limit):
        artifact_id = claim["artifact_id"] if isinstance(claim, dict) else claim
        lease_token = claim.get("lease_token") if isinstance(claim, dict) else None
        try:
            lifecycle.expire(artifact_id, lease_token=lease_token)
            expired += 1
        except Exception as exc:
            failures.append({"artifact_id": artifact_id, "error_code": type(exc).__name__})

    return {"reminders_due": reminders_due, "expired": expired, "failures": failures,
            "expired_challenges_cleared": expired_challenges_cleared}


__all__ = ["run_retention_cycle"]
