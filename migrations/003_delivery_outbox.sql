-- Transactional outbox and retention state for SES/COS side effects.
CREATE TABLE IF NOT EXISTS delivery_events (
    event_id UUID PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    task_id TEXT REFERENCES research_tasks(task_id) ON DELETE RESTRICT,
    user_id UUID REFERENCES users(user_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'send_otp','send_completed','send_expiry','upload_artifact','delete_artifact'
    )),
    status TEXT NOT NULL CHECK (status IN ('pending','running','succeeded','retryable_failed','permanent_failed')),
    attempt_count SMALLINT NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 8),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_until TIMESTAMPTZ,
    lease_token UUID,
    provider_request_id TEXT,
    last_error_code TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON COLUMN delivery_events.payload IS
    'Identifiers and non-sensitive template metadata only; never email, OTP, report content, session token, secret, or signed URL.';

CREATE INDEX IF NOT EXISTS delivery_events_claim_idx
    ON delivery_events (status, available_at, lease_until);

ALTER TABLE task_artifacts
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS delete_attempts SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_delete_error TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS task_artifacts_one_kind
    ON task_artifacts (task_id, kind) WHERE deleted_at IS NULL;
