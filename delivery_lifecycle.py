"""Crash-tolerant publication, expiry and reconciliation orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tencent_delivery import private_object_key


RETENTION = timedelta(days=7)
REMINDER_LEAD = timedelta(days=1)


class DeliveryLifecycle:
    def __init__(self, repository, artifact_store, clock=None):
        self.repository = repository
        self.artifact_store = artifact_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def publish(self, *, task_id, artifact_id, kind, extension, body, content_type):
        """Upload first, then atomically publish DB state and enqueue mail.

        A deterministic key makes a retry overwrite the same object. If the
        process crashes after upload, the reconciler can inspect prepared rows
        and either publish or delete the orphan.
        """
        key = private_object_key(task_id, artifact_id, extension)
        prepared = self.repository.prepare_artifact(
            task_id=task_id, artifact_id=artifact_id, kind=kind,
            object_key=key, content_type=content_type,
        )
        if prepared.get("status") == "published":
            return prepared
        stored = self.artifact_store.upload(key, body, content_type)
        remote = self.artifact_store.stat(key)
        if (remote.get("sha256") != stored.sha256
                or int(remote.get("size_bytes", -1)) != stored.size_bytes
                or remote.get("encryption") != "AES256"):
            raise RuntimeError("COS 上传后完整性或加密校验失败")
        published_at = self.clock()
        return self.repository.publish_artifact_and_complete(
            task_id=task_id, artifact_id=artifact_id, object_key=key,
            sha256=stored.sha256, size_bytes=stored.size_bytes,
            content_type=content_type, etag=stored.etag,
            published_at=published_at, expires_at=published_at + RETENTION,
            remind_at=published_at + RETENTION - REMINDER_LEAD,
            completion_idempotency_key="completed:%s" % task_id,
            reminder_idempotency_key="expiry:%s:%s" % (artifact_id, int((published_at + RETENTION).timestamp())),
        )

    def expire(self, artifact_id):
        """Disable download before attempting remote deletion."""
        artifact = self.repository.mark_delete_pending(artifact_id, now=self.clock())
        if not artifact or artifact.get("status") == "deleted":
            return "already_deleted"
        try:
            self.artifact_store.delete(artifact["object_key"])
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.repository.record_delete_failure(artifact_id, type(exc).__name__)
            raise
        self.repository.mark_deleted(artifact_id, now=self.clock())
        return "deleted"

    def reconcile_prepared(self, limit=100):
        repaired = []
        for artifact in self.repository.stale_prepared(limit=limit, now=self.clock()):
            remote = self.artifact_store.stat_or_none(artifact["object_key"])
            if remote:
                self.repository.record_orphan_for_review(artifact["artifact_id"], remote)
                repaired.append((artifact["artifact_id"], "review"))
            else:
                self.repository.remove_empty_prepared(artifact["artifact_id"])
                repaired.append((artifact["artifact_id"], "removed"))
        return repaired


__all__ = ["DeliveryLifecycle", "RETENTION", "REMINDER_LEAD"]
