"""Explicit P1-P9 worker stage registry.

This registry is metadata only. It prevents the SCF adapter from guessing which
WorkflowService method to call and records the confirmed recovery policy.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StageSpec:
    stage: str
    method: str
    reads: tuple[str, ...]
    writes: str
    recovery: str


STAGE_REGISTRY = (
    StageSpec("P1", "create_intent", ("topic", "tier"), "intent", "stage"),
    StageSpec("P2", "create_plan", ("topic", "intent", "tier"), "plan", "stage"),
    StageSpec("P3", "screen_sources", ("plan", "sources", "tier"), "screening", "stage"),
    StageSpec("P4", "extract_evidence", ("source_record", "question_ids", "tier"), "evidence", "stage"),
    StageSpec("P5", "create_report", ("intent", "plan", "evidence", "tier"), "report", "stage"),
    StageSpec("P6", "create_ppt", ("intent", "report", "evidence", "tier"), "ppt", "stage"),
    StageSpec("P7", "extract_claims", ("report", "ppt", "evidence_ids", "tier"), "claims", "stage"),
    StageSpec("P8", "verify_claims", ("claims", "evidence", "sources", "tier"), "verification", "batch"),
    StageSpec("P9", "assemble_final_deterministic", ("verification", "report", "ppt"), "final_delivery", "deterministic"),
)

BY_STAGE = {spec.stage: spec for spec in STAGE_REGISTRY}


def get_stage_spec(stage: str) -> StageSpec:
    try:
        return BY_STAGE[str(stage).upper()]
    except KeyError as exc:
        raise ValueError("未知工作流阶段") from exc


__all__ = ["StageSpec", "STAGE_REGISTRY", "BY_STAGE", "get_stage_spec"]
