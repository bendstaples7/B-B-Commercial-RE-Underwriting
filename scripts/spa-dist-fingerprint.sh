#!/usr/bin/env bash
# =============================================================================
# spa-dist-fingerprint.sh
# Compute / write a fingerprint for frontend/dist used by Deploy + spa-uptime-canary.
#
# Usage:
#   bash spa-dist-fingerprint.sh compute <DIST_DIR>
#   bash spa-dist-fingerprint.sh write <DIST_DIR> [OUTFILE]
#
# Fingerprint covers index.html bytes + content hashes of referenced /assets/*
# files + DEPLOY_SHA (detects same-name asset overwrites).
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

_hash_file() {
    local f="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$f"
    else
        shasum -a 256 "$f"
    fi
}

compute_fp() {
    {
        _hash_file "$DIST/index.html"
        while IFS= read -r ref; do
            [ -n "$ref" ] || continue
            rel="${ref#/}"
            path="$DIST/$rel"
            if [ -f "$path" ]; then
                _hash_file "$path"
            else
                printf 'MISSING %s\n' "$ref"
            fi
        done < <(grep -oE '/assets/[^"[:space:]]+' "$DIST/index.html" | sort -u || true)
        printf 'DEPLOY_SHA=%s\n' "$DEPLOY_SHA"
    } | {
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum | awk '{print $1}'
        else
            shasum -a 256 | awk '{print $1}'
        fi
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
