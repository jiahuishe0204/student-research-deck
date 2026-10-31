"""Construct the existing workflow service for an SCF invocation."""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from model_routing import ModelRouter
from model_usage import ModelUsageLedger
from patsnap_mcp import DEFAULT_MCP_URL, PatsnapMCPClient
from research_pipeline import search_and_screen_sources
from scf_config import load_scf_config
from scf_stage_dispatch import dispatch_queued_stage
from workflow_service import WorkflowService


def build_workflow(root: str | Path, environ=None, daily_budget_ledger=None, usage_ledger=None) -> WorkflowService:
    """Build WorkflowService from environment-only secrets and project assets."""
    config = load_scf_config(environ)
    root = Path(root)
    router = ModelRouter.from_file(root / "config" / "model-routing.json")
    if usage_ledger is None:
        usage_path = Path(os.environ.get("SCF_USAGE_DB_PATH", "/tmp/model-usage.sqlite3"))
        usage = ModelUsageLedger(usage_path)
    else:
        usage = usage_ledger
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
        daily_budget_ledger=daily_budget_ledger,
    )


def build_queued_stage_dispatcher(environ=None, delivery_publisher_fn=None):
    """Build the offline-testable queued dispatcher from explicit SCF config.

    The factory only constructs clients. It does not make any external request;
    P3 performs provider calls only when the returned dispatcher is invoked.
    """
    env = os.environ if environ is None else environ
    provider = str(env.get("PATENT_PROVIDER", "")).strip().lower()
    options = {"environ": env}

    if provider == "patsnap_mcp_cn":
        key = str(env.get("PATSNAP_MCP_API_KEY", "")).strip()
        if not key:
            raise RuntimeError("已选择智慧芽 MCP，但缺少 PATSNAP_MCP_API_KEY")
        options["patent_client"] = PatsnapMCPClient(
            key,
            env.get("PATSNAP_MCP_URL", DEFAULT_MCP_URL),
            int(env.get("PATSNAP_MCP_TIMEOUT_SECONDS", "30") or 30),
        )
    elif provider not in ("", "epo_ops"):
        raise RuntimeError("SCF 不支持的 PATENT_PROVIDER")

    return partial(
        dispatch_queued_stage,
        research_pipeline_fn=search_and_screen_sources,
        research_pipeline_options=options,
        delivery_publisher_fn=delivery_publisher_fn,
    )


__all__ = ["build_queued_stage_dispatcher", "build_workflow"]
