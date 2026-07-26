#!/usr/bin/env bash
# =============================================================================
# ci-ssh-verify.sh
# Poll SSH to the VPS until connected or SSH_MAX_WAIT_SECONDS is exhausted.
#
# Required env:
#   VPS_USER, VPS_HOST
# Optional env:
#   SSH_KEY_PATH           (default: $HOME/.ssh/id_deploy)
#   SSH_CONNECT_TIMEOUT    (default: 30) — per-attempt ConnectTimeout
#   SSH_MAX_WAIT_SECONDS   (default: 900) — total wait budget
#   SSH_INITIAL_BACKOFF    (default: 5) — seconds before first retry sleep
#
# Exit 0 on success. Exit 1 on budget exhaustion or fail-fast (permission;
# refused after 2 attempts). Prints classified remediation.
# On success writes to GITHUB_OUTPUT when set: ssh_ok=1, ssh_elapsed=<seconds>
# On failure: ssh_ok=0, ssh_class=<timeout|banner|permission|refused|unknown>
# =============================================================================

set -euo pipefail

VPS_USER="${VPS_USER:?VPS_USER required}"
VPS_HOST="${VPS_HOST:?VPS_HOST required}"
SSH_KEY_PATH="${SSH_KEY_PATH:-${HOME}/.ssh/id_deploy}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-30}"
SSH_MAX_WAIT_SECONDS="${SSH_MAX_WAIT_SECONDS:-900}"
SSH_INITIAL_BACKOFF="${SSH_INITIAL_BACKOFF:-5}"

classify_ssh_error() {
  local err="${1:-}"
  local lower
  lower=$(printf '%s' "$err" | tr '[:upper:]' '[:lower:]')
  if printf '%s' "$lower" | grep -qE 'permission denied|publickey|authentication'; then
    echo "permission"
  elif printf '%s' "$lower" | grep -qE 'connection refused|connection reset'; then
    echo "refused"
  elif printf '%s' "$lower" | grep -qE 'banner exchange|kex_exchange|protocol mismatch'; then
    echo "banner"
  elif printf '%s' "$lower" | grep -qE 'timed out|timeout|no route|network is unreachable|could not resolve'; then
    echo "timeout"
  else
    echo "unknown"
  fi
}

print_remediation() {
  local class="$1"
  echo ""
  echo "=== SSH verify failed (class=${class}) ==="
  echo "Host: ${VPS_USER}@${VPS_HOST}"
  case "$class" in
    timeout|banner)
      echo "Likely: VPS/network blip, provider firewall, or sshd overloaded."
      echo "Check: VPS powered on; sshd running; security group / firewall allows GitHub Actions egress to :22;"
      echo "       provider console for host reachability. Re-run Deploy after recovery."
      ;;
    permission)
      echo "Likely: wrong VPS_SSH_KEY / authorized_keys mismatch, or wrong VPS_USER."
      echo "Check: Settings → Secrets (VPS_SSH_KEY, VPS_USER); ~/.ssh/authorized_keys on VPS."
      ;;
    refused)
      echo "Likely: sshd down or not listening on 22."
      echo "Check: systemctl status ssh on VPS; ss -tlnp | grep :22"
      ;;
    *)
      echo "Check: VPS up, sshd, firewall, GitHub secrets (VPS_HOST / VPS_HOST_KEY / VPS_SSH_KEY)."
      ;;
  esac
  echo "See docs/vps-config.md — Deploy SSH / reachability."
}

START_TS=$(date +%s)
DEADLINE=$((START_TS + SSH_MAX_WAIT_SECONDS))
BACKOFF="$SSH_INITIAL_BACKOFF"
ATTEMPT=0
LAST_ERR=""
LAST_CLASS="unknown"

echo "SSH verify: ${VPS_USER}@${VPS_HOST} (ConnectTimeout=${SSH_CONNECT_TIMEOUT}s, max wait=${SSH_MAX_WAIT_SECONDS}s)"

while true; do
  ATTEMPT=$((ATTEMPT + 1))
  NOW=$(date +%s)
  if [ "$NOW" -ge "$DEADLINE" ] && [ "$ATTEMPT" -gt 1 ]; then
    break
  fi
  REMAINING=$((DEADLINE - NOW))
  if [ "$REMAINING" -lt 1 ] && [ "$ATTEMPT" -gt 1 ]; then
    break
  fi

  ERR_FILE=$(mktemp)
  set +e
  OUT=$(ssh -i "${SSH_KEY_PATH}" \
    -o ConnectTimeout="${SSH_CONNECT_TIMEOUT}" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    "${VPS_USER}@${VPS_HOST}" \
    "echo 'SSH connection verified'" 2>"${ERR_FILE}")
  RC=$?
  set -e
  ERR=$(cat "${ERR_FILE}" 2>/dev/null || true)
  rm -f "${ERR_FILE}"

  if [ "$RC" -eq 0 ]; then
    ELAPSED=$(( $(date +%s) - START_TS ))
    echo "${OUT}"
    echo "SSH verify succeeded on attempt ${ATTEMPT} after ${ELAPSED}s."
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
      echo "ssh_ok=1" >> "$GITHUB_OUTPUT"
      echo "ssh_elapsed=${ELAPSED}" >> "$GITHUB_OUTPUT"
      echo "ssh_class=ok" >> "$GITHUB_OUTPUT"
    fi
    exit 0
  fi

  LAST_ERR="$ERR"
  LAST_CLASS=$(classify_ssh_error "$ERR")
  echo "Attempt ${ATTEMPT}: failed (class=${LAST_CLASS}) — ${ERR:-"(no stderr)"}"

  # Non-transient classes: do not burn the full wait budget
  if [ "$LAST_CLASS" = "permission" ]; then
    echo "Non-transient auth failure — failing fast."
    break
  fi
  if [ "$LAST_CLASS" = "refused" ] && [ "$ATTEMPT" -ge 2 ]; then
    echo "Connection refused after ${ATTEMPT} attempts — failing fast."
    break
  fi

  NOW=$(date +%s)
  REMAINING=$((DEADLINE - NOW))
  if [ "$REMAINING" -le 0 ]; then
    break
  fi
  SLEEP_FOR=$BACKOFF
  if [ "$SLEEP_FOR" -gt "$REMAINING" ]; then
    SLEEP_FOR=$REMAINING
  fi
  echo "Sleeping ${SLEEP_FOR}s before retry (${REMAINING}s budget left)..."
  sleep "$SLEEP_FOR"
  # Cap backoff at 60s
  NEXT=$((BACKOFF * 2))
  if [ "$NEXT" -gt 60 ]; then
    BACKOFF=60
  else
    BACKOFF=$NEXT
  fi
done

ELAPSED=$(( $(date +%s) - START_TS ))
print_remediation "$LAST_CLASS"
if [ -n "$LAST_ERR" ]; then
  echo "Last stderr:"
  echo "$LAST_ERR"
fi
# Optional TCP probe for diagnostics
if command -v nc >/dev/null 2>&1; then
  echo "--- TCP probe port 22 ---"
  nc -z -w 5 "$VPS_HOST" 22 && echo "port 22 open" || echo "port 22 closed/unreachable"
elif command -v timeout >/dev/null 2>&1; then
  echo "--- TCP probe port 22 (bash /dev/tcp) ---"
  timeout 5 bash -c "echo >/dev/tcp/${VPS_HOST}/22" 2>/dev/null \
    && echo "port 22 open" || echo "port 22 closed/unreachable"
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "ssh_ok=0" >> "$GITHUB_OUTPUT"
  echo "ssh_elapsed=${ELAPSED}" >> "$GITHUB_OUTPUT"
  echo "ssh_class=${LAST_CLASS}" >> "$GITHUB_OUTPUT"
fi
exit 1
