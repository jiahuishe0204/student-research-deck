# SCF worker deployment notes

## Entry point

```text
scf_entrypoint.main_handler
```

## Required environment variables

```text
DATABASE_URL
DEEPSEEK_API_KEY
MODEL_TASK_MAX_TOTAL_TOKENS
MODEL_TASK_MAX_COST_CNY
```

`DATABASE_URL` and `DEEPSEEK_API_KEY` must be entered in Tencent Cloud's
environment-variable panel. They must not be committed to Git or pasted into
chat messages.

## Dependencies

Install the contents of `requirements-scf.txt` into the deployment package.
The package must include the project Python modules, `config/`, `prompts/`, and
the contract files used by `WorkflowService.from_project`.

## Current boundary

This package is not yet ready to upload: the PostgreSQL schema migration must
be applied first, and the full dependency-size/network smoke test must pass.
