# Suggestion: run Relay's pipelines with Kestra

Relay doesn't need an orchestrator. The worker runs the demo pipeline (`orders_daily`) every weekday at 06:00 and
reports failures to the on-call agent itself (`backend/app/services/pipeline.py`).

Teams that already schedule their data work in [Kestra](https://kestra.io) (or Airflow, Dagster, Prefect) can keep
doing that and still get Relay's on-call agent. Relay only needs two things from the orchestrator:

1. **Build the models** by calling `POST /runner/models/{name}/run` (header `X-Relay-Token`, optional
   `X-Execution-Id`), or by running the SQL in `pipelines/models/` directly.
2. **Report each finished run** to `POST /webhooks/orchestrator` with
   `{"executionId", "namespace", "flowId", "state"}`. `FAILED` opens an incident; `SUCCESS` verifies a pending fix.

Ready-made Kestra 2.x flows are in [`docs/kestra/flows/`](docs/kestra/flows):

| Flow | What it does |
|---|---|
| `data/orders_daily.yml` | Builds `stg_orders` then `fct_revenue` through the runner, daily at 06:00 Asia/Kolkata |
| `relay/notify_relay.yml` | A Flow trigger on `FAILED`, `WARNING` and `SUCCESS` for any flow in the `data` namespace; posts to the webhook |

## Try it locally

Add this service to `docker-compose.yml` (tested with `kestra/kestra:v2.0.3-slim`; the slim image includes the
core HTTP task and Flow trigger these flows use):

```yaml
  kestra:
    image: kestra/kestra:v2.0.3-slim
    command: ["server", "standalone"]
    user: "root"                      # the named volume is root-owned
    environment:
      KESTRA_CONFIGURATION: |
        datasources:
          postgres:
            url: jdbc:postgresql://postgres:5432/kestra
            driverClassName: org.postgresql.Driver
            username: relay
            password: ${POSTGRES_PASSWORD}
        kestra:
          server:
            basic-auth:
              username: admin@relay.dev   # must be an email
              password: RelayAdmin2026    # 8+ chars, an uppercase letter and a number
          repository: { type: postgres }
          queue: { type: postgres }
          storage: { type: local, local: { base-path: /app/storage } }
          url: http://localhost:8080/
    volumes: [kestra-data:/app/storage]
    ports: ["8080:8080"]
    depends_on: { postgres: { condition: service_healthy } }
```

Then:

1. Create the database once: `docker compose exec postgres createdb -U relay kestra`, and add `kestra-data:` under
   `volumes:`.
2. In each flow file, replace `__RELAY_API__` with `http://api:8000` and `__RELAY_TOKEN__` with your
   `RELAY_INGEST_TOKEN`, then import them in the Kestra UI (http://localhost:8080) or with
   `POST /api/v1/main/flows` (content type `application/x-yaml`).
3. To stop Relay's own 06:00 run so the pipeline doesn't run twice, remove `orders_daily` from
   `PIPELINES` in `backend/app/services/pipeline.py`. Keep the `pipeline` resource in the database: the webhook
   uses it to find which team owns the flow.

## Why it isn't in the default stack

- Kestra needs about 1 GB of memory; the rest of Relay runs comfortably in less.
- One fewer service to deploy and secure on Google Cloud.
- The on-call agent only needs a failure signal, which any orchestrator can send. Relay's pitch is
  "works with the orchestrator you already have", not "adopt ours".
