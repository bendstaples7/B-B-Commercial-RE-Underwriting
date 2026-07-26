#!/usr/bin/env bash
# =============================================================================
# ci-http-health-wait.sh
# Poll public /api/health until HTTP 200 + status=healthy or budget exhausted.
#
# Required env:
#   HEALTH_URL   e.g. https://bbanalyzer.duckdns.org/api/health
# Optional env:
#   HTTP_MAX_WAIT_SECONDS  (default: 600)
#   HTTP_CONNECT_TIMEOUT   (default: 5)
#   HTTP_MAX_TIME          (default: 12)
#   HTTP_SLEEP_SECONDS     (default: 5)
#
# Exit 0 on success. Exit 1 on budget exhaustion.
# Writes GITHUB_OUTPUT when set: http_ok=1|0, http_elapsed=<seconds>
# =============================================================================

set -euo pipefail

HEALTH_URL="${HEALTH_URL:?HEALTH_URL required}"
HTTP_MAX_WAIT_SECONDS="${HTTP_MAX_WAIT_SECONDS:-600}"
HTTP_CONNECT_TIMEOUT="${HTTP_CONNECT_TIMEOUT:-5}"
HTTP_MAX_TIME="${HTTP_MAX_TIME:-12}"
HTTP_SLEEP_SECONDS="${HTTP_SLEEP_SECONDS:-5}"

START_TS=$(date +%s)
DEADLINE=$((START_TS + HTTP_MAX_WAIT_SECONDS))
ATTEMPT=0
LAST_STATUS="000"

echo "HTTP health wait: ${HEALTH_URL} (max wait=${HTTP_MAX_WAIT_SECONDS}s)"

while true; do
  ATTEMPT=$((ATTEMPT + 1))
  NOW=$(date +%s)
  if [ "$NOW" -ge "$DEADLINE" ] && [ "$ATTEMPT" -gt 1 ]; then
    break
  fi

  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --connect-timeout "${HTTP_CONNECT_TIMEOUT}" \
    --max-time "${HTTP_MAX_TIME}" \
    "${HEALTH_URL}" 2>/dev/null || echo "000")
  LAST_STATUS="$STATUS"
  echo "Attempt ${ATTEMPT}: HTTP ${STATUS}"

  if [ "$STATUS" = "200" ]; then
    # Require status=healthy. Memory pressure is WARN-only (does not 503);
    # true unavailability returns HTTP 503 (degraded).
    BODY=$(curl -sS --connect-timeout "${HTTP_CONNECT_TIMEOUT}" \
      --max-time "${HTTP_MAX_TIME}" \
      "${HEALTH_URL}" 2>/dev/null || echo "")
    if echo "$BODY" | grep -q '"status"[[:space:]]*:[[:space:]]*"healthy"'; then
      ELAPSED=$(( $(date +%s) - START_TS ))
      echo "Public /api/health OK after ${ELAPSED}s."
      if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "http_ok=1" >> "$GITHUB_OUTPUT"
        echo "http_elapsed=${ELAPSED}" >> "$GITHUB_OUTPUT"
      fi
      exit 0
    fi
    echo "Attempt ${ATTEMPT}: HTTP 200 but status!=healthy — continuing"
    LAST_STATUS="200-degraded"
  fi

  NOW=$(date +%s)
  REMAINING=$((DEADLINE - NOW))
  if [ "$REMAINING" -le 0 ]; then
    break
  fi
  SLEEP_FOR=$HTTP_SLEEP_SECONDS
  if [ "$SLEEP_FOR" -gt "$REMAINING" ]; then
    SLEEP_FOR=$REMAINING
  fi
  sleep "$SLEEP_FOR"
done

ELAPSED=$(( $(date +%s) - START_TS ))
echo ""
echo "=== Public /api/health failed after ${ELAPSED}s (last HTTP ${LAST_STATUS}) ==="
echo "URL: ${HEALTH_URL}"
echo "Likely: site/nginx/gunicorn down, DNS, or network path from GitHub Actions."
echo "Do not assume an app deploy can succeed until this recovers."
echo "See docs/vps-config.md — Deploy SSH / reachability."

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "http_ok=0" >> "$GITHUB_OUTPUT"
  echo "http_elapsed=${ELAPSED}" >> "$GITHUB_OUTPUT"
fi
exit 1
