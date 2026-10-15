#!/bin/sh
# Wipe all data (Postgres + Kestra storage) and start again with fresh demo data.
set -e
cd "$(dirname "$0")/.."
docker compose down -v
cp pipelines/templates/*.sql pipelines/models/
docker compose up -d
echo "Waiting for the API and demo data…"
until curl -sf localhost:8000/health >/dev/null; do sleep 2; done
until docker compose logs worker 2>/dev/null | grep -q "Worker started"; do sleep 2; done
echo "Ready: http://localhost:${WEB_PORT:-3100}"
