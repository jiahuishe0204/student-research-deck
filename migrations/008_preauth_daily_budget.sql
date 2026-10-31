-- Shared conservative budget reservations for anonymous P1 intent requests.
-- Apply only after reviewing production migration and backup readiness.

CREATE TABLE IF NOT EXISTS preauth_daily_budgets (
    budget_day DATE PRIMARY KEY,
    limit_cny NUMERIC(12,6) NOT NULL CHECK (limit_cny > 0),
    reserved_cny NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (reserved_cny >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS preauth_budget_reservations (
    request_id UUID NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 100),
    budget_day DATE NOT NULL REFERENCES preauth_daily_budgets(budget_day),
    reserved_cny NUMERIC(12,6) NOT NULL CHECK (reserved_cny >= 0),
    settled_cny NUMERIC(12,6),
    state TEXT NOT NULL CHECK (state IN ('reserved','settled','unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (request_id, attempt),
    CHECK (settled_cny IS NULL OR settled_cny >= 0)
);

CREATE INDEX IF NOT EXISTS preauth_budget_reservations_day_idx
    ON preauth_budget_reservations (budget_day, state);
