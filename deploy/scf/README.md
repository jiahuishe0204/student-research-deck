# SCF worker deployment notes

## Entry point

```text
scf_entrypoint.main_handler
```

The production deployment contains three explicit entry points:

```text
scf_entrypoint.main_handler             # P1-P9 stage worker
delivery_http_entrypoint.main_handler   # OTP/session/private-download API
delivery_scf_entrypoint.main_handler    # SES outbox/COS retention/reconcile/monitor timers
```

## Required environment variables

```text
DATABASE_URL
DEEPSEEK_API_KEY
MODEL_TASK_MAX_TOTAL_TOKENS
MODEL_TASK_MAX_COST_CNY
IDENTITY_SECRET
EMAIL_FROM
PUBLIC_ORIGIN
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

## Dependencies

Install the contents of `requirements-scf.txt` into the deployment package.
The package must include the project Python modules, `config/`, `prompts/`, and
the contract files used by `WorkflowService.from_project`.

## Current boundary

The offline package and entry points are implemented. Production deployment is
still gated on user authorization, PostgreSQL migration evidence, SES domain
and template approval, a private COS bucket, and the controlled cloud smoke
tests listed in `deploy/tencent/acceptance-evidence-template.md`.
