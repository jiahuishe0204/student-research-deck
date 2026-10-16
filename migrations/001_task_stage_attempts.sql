-- Stage idempotency and restart recovery for the SCF worker.
CREATE TABLE IF NOT EXISTS task_stage_attempts (
    task_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('P1','P2','P3','P4','P5','P6','P7','P8','P9')),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    lease_until DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (task_id, stage, attempt)
);

CREATE INDEX IF NOT EXISTS task_stage_attempts_lease_idx
    ON task_stage_attempts (status, lease_until);
