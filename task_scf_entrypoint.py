"""Timer entrypoint that executes one durable production research job."""

from __future__ import annotations

from pathlib import Path

from delivery_lifecycle import DeliveryLifecycle
from delivery_repository import PostgresDeliveryRepository
from production_artifacts import publish_final_artifacts
from production_config import load_cos_config, load_delivery_common_config
from production_task_queue import PostgresTaskQueue
from production_task_worker import execute_next_job
from scf_app import build_workflow
from scf_config import load_scf_config
from scf_entrypoint import _connect_database
from tencent_delivery import TencentCosArtifactStore


ROOT = Path(__file__).resolve().parent


def main_handler(event, context=None, *, connection=None, workflow=None):
    config = load_scf_config()
    owned = connection is None
    connection = connection or _connect_database(config.database_url)
    try:
        def publisher_factory():
            common = load_delivery_common_config()
            lifecycle = DeliveryLifecycle(
                PostgresDeliveryRepository(connection, common.public_origin),
                TencentCosArtifactStore.from_config(load_cos_config()),
            )
            return lambda task_id, final, payload: publish_final_artifacts(
                lifecycle, task_id, final, payload,
            )
        return execute_next_job(PostgresTaskQueue(connection), workflow or build_workflow(ROOT),
                                root=ROOT, publisher_factory=publisher_factory)
    finally:
        if owned:
            connection.close()


__all__ = ["main_handler"]
