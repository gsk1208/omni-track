#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ART_DIR="${ART_DIR:-$ROOT/artifacts/regression}"
mkdir -p "$ART_DIR"

PORT="${DASHBOARD_PORT:-8090}"
BASE_URL="http://localhost:${PORT}"

note() { printf "[%s] %s\n" "$(date -u +%H:%M:%S)" "$*"; }

# Start dashboard API if not listening.
if ! curl -fsS "${BASE_URL}/api/health" >/dev/null 2>&1; then
  note "Dashboard API not responding on ${BASE_URL}, starting…"
  pushd "$ROOT/mcp" >/dev/null
  # Best-effort seed for dev.
  python3 seed_test_data.py >/dev/null 2>&1 || true

  # Start in background.
  DASHBOARD_PORT="$PORT" nohup python3 dashboard_api.py >"$ROOT/run_dashboard.log" 2>&1 &
  echo $! >"$ROOT/run_dash.pid" || true
  popd >/dev/null

  # Wait up to 10s
  for _ in $(seq 1 20); do
    if curl -fsS "${BASE_URL}/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
fi

note "GET /api/health"
curl -fsS "${BASE_URL}/api/health" | python3 -m json.tool >"$ART_DIR/api_health.json"

note "GET /api/latest"
curl -fsS "${BASE_URL}/api/latest" | python3 -m json.tool >"$ART_DIR/api_latest.json"

note "Playwright: dashboard full-page regression screenshot"
node "$ROOT/scripts/playwright_regression_check.js" >"$ART_DIR/playwright_regression.json"

note "Artifacts written to: $ART_DIR"
cat "$ART_DIR/playwright_regression.json"
