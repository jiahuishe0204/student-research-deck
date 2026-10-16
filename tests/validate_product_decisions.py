import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = ROOT / "config" / "product-decisions.json"


EXPECTED = {
    "authentication_gate": "after_intent_confirmation",
    "authentication_method": "email_one_time_code",
    "email_code_validity_minutes": 10,
    "anonymous_draft_storage": "browser_memory_only",
    "free_entitlement": "one_complete_fast_delivery",
    "eligibility_control": "verified_email_only",
    "deployment_origin": "same_origin_frontend_and_api",
    "internal_test_application_platform": "tencent_edgeone_free_tier",
    "mvp_worker_platform": "tencent_cloud_scf",
    "backend_strategy": "extend_existing_python_service",
    "invocation_model": "sync_control_plane_async_workflow",
    "stage_execution_granularity": "one_recoverable_stage_per_function_p8_batched",
    "stage_trigger_strategy": "database_driven_next_stage_claim",
    "recovery_strategy": "p1_p7_stage_p8_batch_p9_deterministic_assembly",
    "idempotency_strategy": "task_stage_attempt_unique_key",
    "cost_control_strategy": "per_stage_and_per_task_hard_limits",
    "production_database": "managed_postgresql",
    "task_progress": "client_polling_plus_completion_email",
    "delivery": "authenticated_task_page_from_email_link",
    "artifact_retention_days": 7,
    "expiry_reminder_days_before": 1,
    "entitlement_failure_policy": "reserve_then_consume_on_usable_delivery_release_on_technical_failure",
    "payment_timing": "after_free_flow_is_stable",
    "internal_test_cost_strategy": "free_tiers_first",
    "internal_test_postgresql": "managed_free_tier_provider_tbd",
    "internal_test_transactional_email": "free_tier_provider_tbd",
}


def main():
    payload = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    assert payload.get("schema_version") == "1.0.0"
    assert payload.get("decisions") == EXPECTED, "confirmed product decisions changed without updating their contract"
    source = ROOT / payload["source_document"]
    assert source.is_file(), "decision source document is missing"
    assert payload.get("open_clarifications") == []
    deferred = payload.get("explicitly_deferred")
    assert isinstance(deferred, list) and len(deferred) == len(set(deferred))
    assert {"phone_login", "wechat_login", "real_payment", "pptx_generation"}.issubset(deferred)
    print("product decision contract passed")


if __name__ == "__main__":
    main()
