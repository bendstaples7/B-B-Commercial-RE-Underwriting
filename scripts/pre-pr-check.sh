#!/usr/bin/env bash
# Pre-PR readiness gate: clean dev ports, run targeted tests, print review checklist.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${PRE_PR_BASE:-origin/main}"
START_SERVERS="${PRE_PR_START_SERVERS:-1}"
RUN_TESTS="${PRE_PR_RUN_TESTS:-1}"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

kill_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti :"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      yellow "Killing process(es) on port ${port}: ${pids}"
      kill $pids 2>/dev/null || true
      sleep 1
    fi
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  else
    yellow "Could not auto-kill port ${port} (install lsof or fuser)"
  fi
}

wait_for_port() {
  local port="$1"
  local label="$2"
  for _ in $(seq 1 60); do
    if (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1; then
      green "${label} listening on :${port}"
      return 0
    fi
    sleep 1
  done
  red "Timed out waiting for ${label} on :${port}"
  return 1
}

cleanup() {
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Pre-PR check (base: ${BASE}) ==="

echo
echo "--- Duplication / migration guards ---"
python "$ROOT/scripts/check_duplication.py" --base "$BASE"

kill_port 5000
kill_port 3000

if [[ "$START_SERVERS" == "1" ]]; then
  echo
  echo "--- Starting dev servers ---"
  cd "$ROOT"
  python dev.py check
  python dev.py &
  BACKEND_PID=$!
  wait_for_port 5000 "Backend"

  cd "$ROOT/frontend"
  npm run dev -- --host 127.0.0.1 --port 3000 &
  FRONTEND_PID=$!
  wait_for_port 3000 "Frontend"
fi

if [[ "$RUN_TESTS" == "1" ]]; then
  echo
  echo "--- Targeted tests (changed paths vs ${BASE}) ---"
  map_json="$(python "$ROOT/scripts/map_changed_to_tests.py" --base "$BASE" --format json)"
  backend_paths="$(python -c "import json,sys; d=json.load(sys.stdin); print(' '.join(d['backend']))" <<<"$map_json")"
  frontend_paths="$(python -c "import json,sys; d=json.load(sys.stdin); print(' '.join(d['frontend']))" <<<"$map_json")"

  cd "$ROOT/backend"
  if [[ -n "$backend_paths" && "$backend_paths" != "tests/" ]]; then
    yellow "pytest ${backend_paths}"
    pytest -m "not performance" $backend_paths
  elif echo "$map_json" | python -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(p.startswith('backend/') for p in d['changed']) else 1)"; then
    yellow "No specific mapping — running full backend suite (excluding performance)"
    pytest -m "not performance"
  else
    green "No backend changes detected — skipping backend tests"
  fi

  cd "$ROOT/frontend"
  if [[ -n "$frontend_paths" ]]; then
    yellow "vitest ${frontend_paths}"
    npm test -- --run $frontend_paths
  elif echo "$map_json" | python -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(p.startswith('frontend/src/') for p in d['changed']) else 1)"; then
    yellow "No co-located tests — running full frontend suite"
    npm test -- --run
  else
    green "No frontend src changes — skipping frontend tests"
  fi
fi

echo
echo "=== PR readiness checklist ==="
cat "$ROOT/scripts/pre-pr-checklist.txt"

green "Pre-PR check complete."
