-- Unified product identity, task ownership, entitlement, artifact and audit base.
-- Raw email addresses and bearer tokens must never be stored; callers insert
-- keyed hashes produced by the trusted control plane.

CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    email_hash TEXT NOT NULL UNIQUE,
    verified_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_challenges (
    challenge_id UUID PRIMARY KEY,
    email_hash TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    attempts SMALLINT NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    CHECK (expires_at > issued_at)
);

CREATE INDEX IF NOT EXISTS email_challenges_email_idx
    ON email_challenges (email_hash, issued_at DESC);

CREATE TABLE IF NOT EXISTS user_sessions (
    session_hash TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    csrf_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    last_active_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS research_tasks (
    task_id TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id),
    topic TEXT NOT NULL CHECK (char_length(topic) BETWEEN 1 AND 500),
    tier TEXT NOT NULL CHECK (tier IN ('fast','deep')),
    status TEXT NOT NULL CHECK (status IN ('queued','running','cancelled','failed','completed','expired')),
    current_stage TEXT CHECK (current_stage IN ('P1','P2','P3','P4','P5','P6','P7','P8','P9')),
    estimated_cost_cny NUMERIC(10,6) NOT NULL DEFAULT 0 CHECK (estimated_cost_cny >= 0),
    total_tokens BIGINT NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS research_tasks_owner_idx
    ON research_tasks (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS free_entitlements (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('available','reserved','consumed')),
    task_id TEXT UNIQUE REFERENCES research_tasks(task_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((state = 'reserved' AND task_id IS NOT NULL) OR
           (state <> 'reserved' AND task_id IS NULL))
);

CREATE TABLE IF NOT EXISTS task_artifacts (
    artifact_id UUID PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('report','ppt_content','references','export')),
    object_key TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS security_audit_events (
    event_id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES research_tasks(task_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    subject_hash TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS security_audit_events_created_idx
    ON security_audit_events (created_at);
