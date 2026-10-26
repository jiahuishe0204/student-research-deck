-- Shared model-usage reservations across SCF instances.
-- Apply only after backup/production-schema review; no code deploy applies this.

CREATE TABLE IF NOT EXISTS model_usage_attempts (
    request_id UUID NOT NULL,
    attempt SMALLINT NOT NULL CHECK (attempt BETWEEN 1 AND 100),
    task_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('P1A','P1B','P1','P2A','P2B','P2','P3','P4','P5','P6','P7','P8','P9')),
    model TEXT NOT NULL,
    effort TEXT NOT NULL,
    budget_state TEXT NOT NULL CHECK (budget_state IN ('reserved','settled','unknown','released')),
    reserved_cost_cny NUMERIC(12,6) NOT NULL CHECK (reserved_cost_cny >= 0),
    actual_cost_cny NUMERIC(12,6) CHECK (actual_cost_cny IS NULL OR actual_cost_cny >= 0),
    reserved_input_tokens BIGINT NOT NULL DEFAULT 0 CHECK (reserved_input_tokens >= 0),
    reserved_output_tokens BIGINT NOT NULL DEFAULT 0 CHECK (reserved_output_tokens >= 0),
    reserved_total_tokens BIGINT NOT NULL DEFAULT 0 CHECK (reserved_total_tokens >= 0),
    prompt_tokens BIGINT NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens BIGINT NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    total_tokens BIGINT NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    cache_hit_tokens BIGINT NOT NULL DEFAULT 0 CHECK (cache_hit_tokens >= 0),
    cache_miss_tokens BIGINT NOT NULL DEFAULT 0 CHECK (cache_miss_tokens >= 0),
    reasoning_tokens BIGINT NOT NULL DEFAULT 0 CHECK (reasoning_tokens >= 0),
    result_status TEXT NOT NULL,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (request_id, attempt)
);

CREATE INDEX IF NOT EXISTS model_usage_attempts_task_idx
    ON model_usage_attempts (task_id, created_at);
CREATE INDEX IF NOT EXISTS model_usage_attempts_state_idx
    ON model_usage_attempts (budget_state, updated_at);
