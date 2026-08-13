#!/usr/bin/env bash
# =============================================================================
# ensure_frontend_dist_readable.sh
# Make frontend/dist world-traversable/readable for nginx (www-data) and fail
# closed if index.html asset refs are not other-readable.
#
# Usage (from APP_DIR or with absolute path):
#   bash ensure_frontend_dist_readable.sh [DIST_DIR]
#   bash ensure_frontend_dist_readable.sh [DIST_DIR] --http-base URL
#
# Example:
#   bash /home/deploy/ensure_frontend_dist_readable.sh frontend/dist
#   bash /home/deploy/ensure_frontend_dist_readable.sh frontend/dist --http-base http://127.0.0.1
# =============================================================================

set -euo pipefail

DIST="frontend/dist"
HTTP_BASE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --http-base)
            shift
            HTTP_BASE="${1:-}"
            if [ -z "$HTTP_BASE" ]; then
                echo "FAILED: --http-base requires a URL"
                exit 1
            fi
            ;;
        -*)
            echo "FAILED: unknown option: $1"
            exit 1
            ;;
        *)
            DIST="$1"
            ;;
    esac
    shift
done

if [ ! -d "$DIST" ]; then
    echo "FAILED: frontend dist missing: $DIST"
    exit 1
fi
if [ ! -f "$DIST/index.html" ]; then
    echo "FAILED: missing $DIST/index.html"
    exit 1
fi

# nginx runs as www-data; mode 0700 on assets/ yields HTTP 404 while files exist.
chmod -R a+rX "$DIST"

# Prefer numeric mode (Linux deploy VPS). last octal digit = other bits.
check_other_bits() {
    local path="$1"
    local mode other
    mode=$(stat -c '%a' "$path" 2>/dev/null || stat -f '%OLp' "$path" 2>/dev/null || echo "")
    if [ -z "$mode" ]; then
        echo "FAILED: could not stat mode for $path"
        return 1
    fi
    other=$((10#$mode % 10))
    if [ -d "$path" ]; then
        # directories need other+x so www-data can traverse
        if [ $((other & 1)) -ne 1 ]; then
            return 1
        fi
        return 0
    fi
    # files need other+r
    if [ $((other & 4)) -ne 4 ]; then
        return 1
    fi
    return 0
}

if ! check_other_bits "$DIST"; then
    echo "FAILED: $DIST is not other-executable (nginx cannot traverse)"
    ls -ld "$DIST"
    exit 1
fi

ASSET_REFS=()
while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    ASSET_REFS+=("$ref")
done < <(python3 - "$DIST/index.html" <<'PY'
import sys
from html.parser import HTMLParser


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = set()

    def handle_starttag(self, tag, attrs):
        if tag not in {"script", "link"}:
            return
        attr_name = "src" if tag == "script" else "href"
        values = dict(attrs)
        value = values.get(attr_name)
        if not value:
            return
        ref = value.split("?", 1)[0].split("#", 1)[0]
        if ref.startswith("assets/"):
            ref = f"/{ref}"
        if ref.startswith("/assets/"):
            self.refs.add(ref)


parser = AssetParser()
with open(sys.argv[1], encoding="utf-8") as fh:
    parser.feed(fh.read())
for ref in sorted(parser.refs):
    print(ref)
PY
)

if [ "${#ASSET_REFS[@]}" -eq 0 ]; then
    echo "FAILED: no /assets/ refs in $DIST/index.html"
    exit 1
fi

for ref in "${ASSET_REFS[@]}"; do
    rel="${ref#/}"
    path="$DIST/$rel"
    parent=$(dirname "$path")
    if [ ! -f "$path" ]; then
        echo "FAILED: missing asset on disk: $path"
        exit 1
    fi
    if ! check_other_bits "$parent"; then
        echo "FAILED: asset parent not other-executable (nginx 404 class): $parent"
        ls -ld "$parent"
        exit 1
    fi
    if ! check_other_bits "$path"; then
        echo "FAILED: asset not other-readable: $path"
        ls -l "$path"
        exit 1
    fi
done

echo "OK: $DIST world-readable for nginx (${#ASSET_REFS[@]} asset ref(s))"

if [ -n "$HTTP_BASE" ]; then
    base="${HTTP_BASE%/}"
    host_header=""
    if ls /etc/nginx/sites-enabled/* >/dev/null 2>&1; then
        host_header=$(grep -h -m1 -E '^\s*server_name\s+' /etc/nginx/sites-enabled/* 2>/dev/null \
            | awk '{print $2}' | tr -d ';' | head -1 || true)
        case "$host_header" in
            ""|_|localhost|*\**) host_header="" ;;
        esac
    fi
    for ref in "${ASSET_REFS[@]}"; do
        url="${base}${ref}"
        # Follow HTTPS redirects (VPS nginx 301 http→https); -k for localhost TLS.
        if [ -n "$host_header" ]; then
            code=$(curl -skL -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 15 \
                --max-redirs 5 -H "Host: ${host_header}" "$url" 2>/dev/null || echo "000")
        else
            code=$(curl -skL -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 15 \
                --max-redirs 5 "$url" 2>/dev/null || echo "000")
        fi
        if [ "$code" != "200" ]; then
            echo "FAILED: HTTP $code for $url (Host=${host_header:-none}) — nginx cannot serve asset"
            exit 1
        fi
    done
    echo "OK: HTTP 200 for ${#ASSET_REFS[@]} asset(s) via ${base}"
fi
