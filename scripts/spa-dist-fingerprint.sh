#!/usr/bin/env bash
# =============================================================================
# spa-dist-fingerprint.sh
# Compute / write a fingerprint for frontend/dist used by Deploy + spa-uptime-canary.
#
# Usage:
#   bash spa-dist-fingerprint.sh compute <DIST_DIR>
#   bash spa-dist-fingerprint.sh write <DIST_DIR> [OUTFILE]
#
# Fingerprint covers index.html bytes + ordered /assets/ hrefs from HTML + DEPLOY_SHA.
# =============================================================================

set -euo pipefail

CMD="${1:?usage: compute|write DIST [OUTFILE]}"
DIST="${2:?DIST required}"
OUTFILE="${3:-/home/deploy/spa-dist.fingerprint}"
APP_DIR="${APP_DIR:-/home/deploy/app}"

if [ ! -f "$DIST/index.html" ]; then
    echo "FAILED: missing $DIST/index.html" >&2
    exit 1
fi

DEPLOY_SHA="unknown"
if [ -f "$APP_DIR/DEPLOY_SHA" ]; then
    DEPLOY_SHA="$(tr -d '[:space:]' < "$APP_DIR/DEPLOY_SHA" || echo unknown)"
fi

compute_fp() {
    {
        sha256sum "$DIST/index.html" 2>/dev/null || shasum -a 256 "$DIST/index.html"
        grep -oE '/assets/[^"[:space:]]+' "$DIST/index.html" | sort -u || true
        printf 'DEPLOY_SHA=%s\n' "$DEPLOY_SHA"
    } | sha256sum 2>/dev/null | awk '{print $1}' \
      || {
        {
            shasum -a 256 "$DIST/index.html"
            grep -oE '/assets/[^"[:space:]]+' "$DIST/index.html" | sort -u || true
            printf 'DEPLOY_SHA=%s\n' "$DEPLOY_SHA"
        } | shasum -a 256 | awk '{print $1}'
      }
}

case "$CMD" in
    compute)
        compute_fp
        ;;
    write)
        fp="$(compute_fp)"
        printf '%s\n' "$fp" > "$OUTFILE"
        printf '%s\n' "$fp"
        ;;
    *)
        echo "FAILED: unknown command $CMD (use compute|write)" >&2
        exit 1
        ;;
esac
