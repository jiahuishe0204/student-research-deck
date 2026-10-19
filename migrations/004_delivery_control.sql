-- Shared anti-abuse counters and delivery scheduling fields.
CREATE TABLE IF NOT EXISTS security_rate_limits (
    dimension TEXT NOT NULL CHECK (dimension IN ('ip','email','ip_email','global')),
    subject_hash TEXT NOT NULL,
    window_started_at TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    blocked_until TIMESTAMPTZ,
    PRIMARY KEY (dimension, subject_hash)
);

ALTER TABLE task_artifacts
    ADD COLUMN IF NOT EXISTS remind_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS orphan_review_required BOOLEAN NOT NULL DEFAULT FALSE;

-- Production code must insert these events in the same transaction that marks
-- the artifact published and consumes a reserved entitlement.
CREATE UNIQUE INDEX IF NOT EXISTS one_completion_mail_per_task
    ON delivery_events (task_id, event_type) WHERE event_type='send_completed';
