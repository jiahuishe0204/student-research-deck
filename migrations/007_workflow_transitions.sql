-- Retry stage-to-stage orchestration without repeating an already-paid model job.

ALTER TABLE research_task_jobs
    ADD COLUMN IF NOT EXISTS transition_status TEXT NOT NULL DEFAULT 'not_ready';
ALTER TABLE research_task_jobs
    ADD COLUMN IF NOT EXISTS transition_attempts SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE research_task_jobs
    ADD COLUMN IF NOT EXISTS transition_error TEXT;

ALTER TABLE research_task_jobs DROP CONSTRAINT IF EXISTS research_task_jobs_transition_status_check;
ALTER TABLE research_task_jobs ADD CONSTRAINT research_task_jobs_transition_status_check
    CHECK (transition_status IN ('not_ready','pending','running','done'));
ALTER TABLE research_task_jobs DROP CONSTRAINT IF EXISTS research_task_jobs_transition_attempts_check;
ALTER TABLE research_task_jobs ADD CONSTRAINT research_task_jobs_transition_attempts_check
    CHECK (transition_attempts BETWEEN 0 AND 3);

CREATE INDEX IF NOT EXISTS research_task_jobs_transition_idx
    ON research_task_jobs (transition_status, available_at, lease_until, updated_at);
