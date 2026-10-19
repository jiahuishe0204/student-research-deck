"""Authorized control-plane operations for private delivery artifacts."""

from __future__ import annotations

from datetime import datetime, timezone


class DeliveryAccessError(PermissionError):
    pass


def issue_download(repository, artifact_store, *, user_id, task_id, artifact_id,
                   filename, now=None):
    """Issue one short URL only after a single owner-bound repository lookup."""
    instant = now or datetime.now(timezone.utc)
    artifact = repository.authorized_artifact(user_id=user_id, task_id=task_id,
                                              artifact_id=artifact_id, now=instant)
    if not artifact:
        # Deliberately identical for missing, other owner, expired and deleted.
        raise DeliveryAccessError("交付文件不存在或已失效")
    if artifact.get("status") != "published" or not artifact.get("downloadable"):
        raise DeliveryAccessError("交付文件不存在或已失效")
    expires_at = artifact.get("expires_at")
    if not expires_at or instant >= expires_at:
        raise DeliveryAccessError("交付文件不存在或已失效")
    return artifact_store.signed_download_before(
        artifact["object_key"], filename, expires_at, instant
    )


__all__ = ["DeliveryAccessError", "issue_download"]
