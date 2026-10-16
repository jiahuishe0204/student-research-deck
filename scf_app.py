"""Construct the existing workflow service for an SCF invocation."""

from __future__ import annotations

import os
from pathlib import Path

from model_routing import ModelRouter
from model_usage import ModelUsageLedger
from scf_config import load_scf_config
from workflow_service import WorkflowService


def build_workflow(root: str | Path, environ=None) -> WorkflowService:
    """Build WorkflowService from environment-only secrets and project assets."""
    config = load_scf_config(environ)
    root = Path(root)
    router = ModelRouter.from_file(root / "config" / "model-routing.json")
    usage_path = Path(os.environ.get("SCF_USAGE_DB_PATH", "/tmp/model-usage.sqlite3"))
    usage = ModelUsageLedger(usage_path)
    return WorkflowService.from_project(
        config.deepseek_api_key,
        router,
        root,
        usage_ledger=usage,
        model_limits={
            "task_max_cost_cny": config.task_max_cost_cny,
            "task_max_total_tokens": config.task_max_total_tokens,
            "pro_max_calls": int((environ or os.environ).get("MODEL_PRO_MAX_CALLS", "0") or 0),
            "pro_max_output_tokens": int((environ or os.environ).get("MODEL_PRO_MAX_OUTPUT_TOKENS", "0") or 0),
            "pro_max_total_tokens": int((environ or os.environ).get("MODEL_PRO_MAX_TOTAL_TOKENS", "0") or 0),
        },
    )


__all__ = ["build_workflow"]
