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
MODEL_PRICES_CNY_PER_MILLION (optional JSON; explicit provider CNY-per-million-token schedule)
IDENTITY_SECRET
EMAIL_FROM
PUBLIC_ORIGIN
EDGEONE_GATEWAY_SECRET
PREAUTH_INTENT_SIGNING_SECRET
SES_REGION
SES_TEMPLATE_OTP
SES_TEMPLATE_COMPLETED
SES_TEMPLATE_EXPIRY
COS_REGION
COS_BUCKET
```

Bind `ResearchdeskSesOutboxScfRole` to the SES outbox function and
`ResearchdeskCosDeliveryScfRole` to the download, task worker, and retention
functions. SCF supplies `TENCENTCLOUD_SECRETID`, `TENCENTCLOUD_SECRETKEY`, and
`TENCENTCLOUD_SESSIONTOKEN` at runtime. The adapters use this complete triplet
for SES and COS signing. Never copy these temporary values into function
configuration or logs. The two new roles have distinct least-privilege CAM
policies. Other application secrets remain server-side only and must not be
committed to Git, placed in public EdgeOne code, or pasted into chat messages.

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

The checked-in CI workflow builds a Linux/Python 3.13 candidate ZIP from the
current Git commit, installs `requirements-scf.txt` into that package, and
smoke-imports the unpacked entry points. Its short-lived artifact is a
deployment candidate, not an automatic release. Inspect `bundle-manifest.json`
and verify its commit matches the approved PR head before manual SCF upload.
The older ignored ZIP in this checkout predates the anonymous P1 modules and
must not be uploaded as a substitute. Local task databases and generated ZIPs
are not included in the candidate source selection.

## Current boundary

The offline package and entry points are implemented. The user authorized the
Guangzhou SCF/COS deployment and server-side injection of existing credentials,
with a CNY 100 ceiling for this phase. The private COS bucket, lifecycle rule,
SES domain and sender, and two dedicated SCF roles have been configured. The
three SES templates remain under review. Production deployment still requires
a fresh PostgreSQL snapshot check and sustained backup plan, a verified Python 3.13
candidate bundle, function/trigger binding, and controlled cloud smoke tests
listed in `deploy/tencent/acceptance-evidence-template.md`.

The production timer worker is `task_scf_entrypoint.main_handler`. It now builds
the workflow with shared PostgreSQL pre-auth budget and model-usage ledgers;
verify that migrations `008_preauth_daily_budget.sql` and
`010_shared_model_usage_budget.sql` are present before deploying this code.
Migration `009_partial_task_status.sql` is also required before enabling
partial-delivery status. Code deployment does not apply database migrations.
The 2026-11-01 production read-only audit found the final schema target for
migrations 001-010 and an isolated logical restore passed. Recheck the live
schema snapshot before release; the audit does not prove write behavior.

Model reservations remain conservative: peak miss-price for all prompt tokens
and the configured maximum output. Settled attempts use returned cache-hit,
cache-miss, and output usage against `MODEL_PRICES_CNY_PER_MILLION`; this
schedule must contain verified peak rates. Settled values are conservative
ledger calculations, not provider invoices. At reservation time and settlement,
the worker applies the Beijing weekday peak window (09:00-12:00, 14:00-18:00)
or the half-price valley multiplier. A valley reservation whose request timeout
reaches the next peak is reserved at peak; settlement uses the attempt's stored
creation time. Without a holiday calendar, weekdays are conservatively treated
as normal workdays. If unset, the checked-in fallback schedule applies. Unknown
provider outcomes remain reserved.
