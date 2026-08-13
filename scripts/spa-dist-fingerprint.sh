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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSET_REFS_SCRIPT="/home/deploy/spa_asset_refs.py"
if [ ! -f "$ASSET_REFS_SCRIPT" ]; then
    ASSET_REFS_SCRIPT="$SCRIPT_DIR/spa_asset_refs.py"
fi

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
        sha256sum "$f" | awk '{print $1}'
    else
        shasum -a 256 "$f" | awk '{print $1}'
    fi
}

compute_fp() {
    {
        printf 'index.html %s\n' "$(_hash_file "$DIST/index.html")"
        while IFS= read -r ref; do
            [ -n "$ref" ] || continue
            rel="${ref#/}"
            path="$DIST/$rel"
            if [ -f "$path" ]; then
                printf '%s %s\n' "$rel" "$(_hash_file "$path")"
            else
                printf 'MISSING %s\n' "$ref"
            fi
        done < <(python3 "$ASSET_REFS_SCRIPT" "$DIST/index.html")
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
        tmp="${OUTFILE}.$$.$RANDOM.tmp"
        if ! printf '%s\n' "$fp" > "$tmp" || ! mv -f "$tmp" "$OUTFILE"; then
            rm -f "$tmp" 2>/dev/null || true
            echo "FAILED: could not atomically write $OUTFILE" >&2
            exit 1
        fi
        printf '%s\n' "$fp"
        ;;
    *)
        echo "FAILED: unknown command $CMD (use compute|write)" >&2
        exit 1
        ;;
esac
