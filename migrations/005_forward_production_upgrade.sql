-- Forward-only upgrade for environments that already ran migrations 001-004.
-- Existing numbered migrations remain immutable; all additions are idempotent.

ALTER TABLE task_stage_attempts ADD COLUMN IF NOT EXISTS lease_token UUID;
UPDATE task_stage_attempts SET lease_token=gen_random_uuid() WHERE lease_token IS NULL;
ALTER TABLE task_stage_attempts ALTER COLUMN lease_token SET NOT NULL;

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_ciphertext BYTEA;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_key_version SMALLINT;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM users WHERE email_ciphertext IS NULL OR email_key_version IS NULL) THEN
        RAISE EXCEPTION 'legacy users require explicit encrypted-email backfill before upgrade';
    END IF;
END $$;
ALTER TABLE users ALTER COLUMN email_ciphertext SET NOT NULL;
ALTER TABLE users ALTER COLUMN email_key_version SET NOT NULL;

ALTER TABLE email_challenges ADD COLUMN IF NOT EXISTS email_ciphertext BYTEA;
ALTER TABLE email_challenges ADD COLUMN IF NOT EXISTS code_ciphertext BYTEA;
ALTER TABLE email_challenges ADD COLUMN IF NOT EXISTS email_key_version SMALLINT NOT NULL DEFAULT 1;

ALTER TABLE delivery_events DROP CONSTRAINT IF EXISTS delivery_events_status_check;
ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS lease_token UUID;
ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;
ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS provider_request_id TEXT;
ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS last_error_code TEXT;
ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS attempt_count SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE delivery_events ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE delivery_events ADD CONSTRAINT delivery_events_status_check
    CHECK (status IN ('pending','running','succeeded','retryable_failed','permanent_failed','unknown'));
ALTER TABLE delivery_events DROP CONSTRAINT IF EXISTS delivery_events_task_id_fkey;
ALTER TABLE delivery_events DROP CONSTRAINT IF EXISTS delivery_events_user_id_fkey;
ALTER TABLE delivery_events ADD CONSTRAINT delivery_events_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES research_tasks(task_id) ON DELETE RESTRICT;
ALTER TABLE delivery_events ADD CONSTRAINT delivery_events_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS delivery_events_claim_idx
    ON delivery_events (status, available_at, lease_until);

ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS sha256 TEXT;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS content_type TEXT;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS etag TEXT;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'prepared';
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS downloadable BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS remind_at TIMESTAMPTZ;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS orphan_review_required BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS delete_attempts SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS last_delete_error TEXT;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS delete_lease_token UUID;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS delete_lease_until TIMESTAMPTZ;
ALTER TABLE task_artifacts ADD COLUMN IF NOT EXISTS delete_next_attempt_at TIMESTAMPTZ;

ALTER TABLE task_artifacts DROP CONSTRAINT IF EXISTS task_artifacts_task_id_fkey;
ALTER TABLE task_artifacts ADD CONSTRAINT task_artifacts_task_id_fkey
    FOREIGN KEY (task_id) REFERENCES research_tasks(task_id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS task_artifacts_delete_claim_idx
    ON task_artifacts (status, expires_at, delete_next_attempt_at, delete_lease_until);
