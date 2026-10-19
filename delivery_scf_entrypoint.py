"""Tencent SCF entrypoint for SES outbox and COS retention timers."""

from __future__ import annotations

from delivery_lifecycle import DeliveryLifecycle
from delivery_outbox import recover_expired_email_leases
from delivery_repository import PostgresDeliveryRepository
from delivery_worker import execute_one
from identity_vault import IdentityVault
from production_config import load_production_config
from retention_worker import run_retention_cycle
from tencent_delivery import TencentCosArtifactStore, TencentSesMailer


class DeliveryAttentionRequired(RuntimeError):
    pass


def _dependencies():  # pragma: no cover - real SCF smoke path
    import psycopg
    config = load_production_config()
    connection = psycopg.connect(config.database_url)
    repository = PostgresDeliveryRepository(connection, config.public_origin)
    store = TencentCosArtifactStore.from_config(config)
    return {
        "connection": connection,
        "repository": repository,
        "vault": IdentityVault(config.identity_secret, repository),
        "mailer": TencentSesMailer.from_config(config),
        "lifecycle": DeliveryLifecycle(repository, store),
    }


def main_handler(event, context=None, *, dependencies=None):
    deps = dependencies or _dependencies()
    action = str((event or {}).get("action", "outbox"))
    try:
        if action == "outbox":
            quarantined = recover_expired_email_leases(deps["connection"])
            result = execute_one(deps["connection"], deps["vault"], deps["mailer"])
            if quarantined:
                raise DeliveryAttentionRequired("发现邮件发送结果未知事件：%d" % len(quarantined))
            if result.get("status") in ("unknown", "permanent_failed"):
                raise DeliveryAttentionRequired("邮件事件需要人工处理：%s" % result["status"])
            return {"ok": True, "action": action, "quarantined_count": len(quarantined), **result}
        if action == "retention":
            result = run_retention_cycle(deps["repository"], deps["lifecycle"])
            if result["failures"]:
                raise DeliveryAttentionRequired("COS 删除失败：%d" % len(result["failures"]))
            return {"ok": True, "action": action, **result}
        if action == "reconcile":
            repaired = deps["lifecycle"].reconcile_prepared()
            return {"ok": True, "action": action, "reviewed_count": len(repaired)}
        if action == "monitor":
            counts = deps["repository"].delivery_attention_counts()
            if any(counts.values()):
                raise DeliveryAttentionRequired("交付积压需要处理：%s" % counts)
            return {"ok": True, "action": action, **counts}
        raise ValueError("未知交付任务类型")
    finally:
        if dependencies is None:
            deps["connection"].close()


__all__ = ["DeliveryAttentionRequired", "main_handler"]
