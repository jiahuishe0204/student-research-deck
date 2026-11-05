-- Allow an evidence-limited but usable delivery, as confirmed in the product decisions.
-- Apply after the existing production migrations; do not edit already-applied migrations.

ALTER TABLE research_tasks
    DROP CONSTRAINT IF EXISTS research_tasks_status_check;

ALTER TABLE research_tasks
    ADD CONSTRAINT research_tasks_status_check
    CHECK (status IN ('queued','running','cancelled','failed','completed','partial','expired'));
