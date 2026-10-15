# Demo pipeline

`models/*.sql` are the warehouse models that Kestra's `data.orders_daily` flow builds (through the API's
`/runner/models/{name}/run`). `templates/` holds the original versions; `POST /demo/pipeline/reset` copies them back.

When the on-call agent's fix is approved, the corrected SQL is written to `models/` (or merged on GitHub when
`GITHUB_TOKEN`/`GITHUB_REPO` are set).
