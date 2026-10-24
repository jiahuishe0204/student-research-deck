-- Durable production queue for browser-created research tasks.
-- Jobs are claimed with SKIP LOCKED and fenced by a lease token.

CREATE TABLE IF NOT EXISTS research_task_jobs (
    job_id UUID PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE RESTRICT,
    job_key TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('P1','P2','P3','P4','P5','P6','P7','P8','P9')),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt BETWEEN 0 AND 3),
    status TEXT NOT NULL CHECK (status IN
        ('pending','running','succeeded','retryable_failed','permanent_failed','cancelled')),
    payload JSONB NOT NULL,
    result JSONB,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, job_key)
);

CREATE INDEX IF NOT EXISTS research_task_jobs_claim_idx
    ON research_task_jobs (status, available_at, lease_until, created_at);

CREATE INDEX IF NOT EXISTS research_task_jobs_task_idx
    ON research_task_jobs (task_id, created_at);
