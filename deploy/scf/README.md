# SCF worker deployment notes

## Entry point

```text
scf_entrypoint.main_handler
```

The production deployment contains explicit entry points:

```text
scf_entrypoint.main_handler             # P1-P9 stage worker
task_scf_entrypoint.main_handler        # PostgreSQL queued-task timer worker
delivery_http_entrypoint.main_handler   # OTP/session/private-download API
intent_http_entrypoint.main_handler     # anonymous P1 HTTP API
delivery_scf_entrypoint.main_handler    # SES outbox/COS retention/reconcile/monitor timers
```

## Required environment variables

```text
DATABASE_URL
DEEPSEEK_API_KEY
PATENT_PROVIDER
PATSNAP_MCP_URL
PATSNAP_MCP_API_KEY
PATSNAP_MCP_TIMEOUT_SECONDS
MODEL_TASK_MAX_TOTAL_TOKENS
MODEL_TASK_MAX_COST_CNY
IDENTITY_SECRET
EMAIL_FROM
PUBLIC_ORIGIN
EDGEONE_GATEWAY_SECRET
PREAUTH_INTENT_SIGNING_SECRET
SES_SECRET_ID
SES_SECRET_KEY
SES_REGION
SES_TEMPLATE_OTP
SES_TEMPLATE_COMPLETED
SES_TEMPLATE_EXPIRY
COS_SECRET_ID
COS_SECRET_KEY
COS_REGION
COS_BUCKET
```

Secrets must be injected by the Tencent Cloud server-side secret facility or
SCF role. They must not be committed to Git, placed in public EdgeOne code, or
pasted into chat messages. SES and COS credentials must belong to separate
least-privilege CAM identities.

`EDGEONE_GATEWAY_SECRET` must be the same high-entropy secret in the EdgeOne
project and the five HTTP control-plane functions. The SCF endpoints reject
requests that do not carry it. EdgeOne overwrites `X-EdgeOne-Client-IP` from
its trusted runtime context before proxying, so OTP rate limits use the actual
client IP instead of an EdgeOne egress address.

The HTTP entry points use SCF Function URLs, not the retired API Gateway
trigger. Configure the URLs as HTTPS public endpoints with SCF CORS disabled;
the shared gateway secret is still mandatory at the application layer. Store
the five URL origins in EdgeOne as `HEALTH_API_BASE_URL`, `AUTH_API_BASE_URL`,
`INTENT_API_BASE_URL`, `TASK_API_BASE_URL`, and `DELIVERY_API_BASE_URL`. Do not expose them to browser
code or reuse the COS-enabled download function for auth/task routes.

## Dependencies

Install the contents of `requirements-scf.txt` into the deployment package.
The package must include the project Python modules, `config/`, `prompts/`, and
the contract files used by `WorkflowService.from_project`.

## Current boundary

The offline package and entry points are implemented. Production deployment is
still gated on user authorization, PostgreSQL migration evidence, SES domain
and template approval, a private COS bucket, and the controlled cloud smoke
tests listed in `deploy/tencent/acceptance-evidence-template.md`.

The production timer worker is `task_scf_entrypoint.main_handler`. It now builds
the workflow with shared PostgreSQL pre-auth budget and model-usage ledgers;
verify that migrations `008_preauth_daily_budget.sql` and
`010_shared_model_usage_budget.sql` are present before deploying this code.
Migration `009_partial_task_status.sql` is also required before enabling
partial-delivery status. Code deployment does not apply database migrations.
The project notes record migration 008 as previously applied to the internal
Neon database, but live schema state must be re-verified before release.
