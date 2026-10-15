# Demo pipeline

`models/*.sql` are the warehouse models of the `orders_daily` pipeline. The worker runs them daily at 06:00
(`backend/app/services/pipeline.py`); an external orchestrator can run them through `/runner/models/{name}/run`. `templates/` holds the original versions; `POST /demo/pipeline/reset` copies them back.

When the on-call agent's fix is approved, the corrected SQL is written to `models/` (or merged on GitHub when
`GITHUB_TOKEN`/`GITHUB_REPO` are set).
