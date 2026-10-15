#!/bin/sh
# Fill Relay with a ready-to-present demo by playing demo/scenario.json through the real pipeline.
#
#   ./scripts/seed-demo.sh                  play the scenario on the current data
#   ./scripts/seed-demo.sh --fresh          wipe everything first (same as reset-demo.sh), then play it
#   ./scripts/seed-demo.sh --all            also process the sample meeting, break the pipeline, start Meera's focus
#   ./scripts/seed-demo.sh --fresh --all    the full demo state from scratch (about 2 minutes with Gemini)
set -e
cd "$(dirname "$0")/.."
FLAGS=""
for arg in "$@"; do
  case "$arg" in
    --fresh) ./scripts/reset-demo.sh ;;
    --all) FLAGS="$FLAGS --meeting --incident --focus meera@acme.test" ;;
    *) FLAGS="$FLAGS $arg" ;;
  esac
done
docker compose up -d >/dev/null
until curl -sf localhost:8000/health >/dev/null; do sleep 2; done
docker compose exec -T api python -m app.demo_seed /app/demo/scenario.json $FLAGS
