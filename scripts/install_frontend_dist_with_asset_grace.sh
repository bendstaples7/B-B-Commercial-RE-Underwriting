#!/usr/bin/env bash
# install_frontend_dist_with_asset_grace.sh
#
# Install a CI-built SPA dist while retaining the previous build's hashed
# /assets files for one deploy generation. Open tabs that still reference old
# chunk URLs keep working until they refresh.
#
# Usage:
#   bash install_frontend_dist_with_asset_grace.sh \
#     <NEW_DIST> <LIVE_DIST> [PREV_ASSETS_DIR]
#
# Example (from deploy.sh):
#   bash scripts/install_frontend_dist_with_asset_grace.sh \
#     /home/deploy/frontend-dist frontend/dist /home/deploy/frontend-assets-prev
#
# Flow:
#   1. Snapshot NEW/assets → PREV_ASSETS.next (pure this-build hashes only)
#   2. Overlay previous PREV_ASSETS into NEW/assets (no overwrite)
#   3. Stage the complete tree under dist-releases/<id>
#   4. Atomically switch LIVE_DIST symlink to the new release (nginx path never
#      vanishes; no in-place partial tree)
#   5. Leave PREV_ASSETS.next for deploy.sh to promote AFTER full success

set -euo pipefail

NEW_DIST="${1:?new dist dir required}"
LIVE_DIST="${2:?live dist dir required}"
PREV_ASSETS="${3:-/home/deploy/frontend-assets-prev}"
PREV_ASSETS_NEXT="${PREV_ASSETS}.next"
# Optional: path that rollback restores from (may be a copy or a symlink into releases).
DIST_BACKUP="${FRONTEND_DIST_BACKUP:-/home/deploy/frontend-dist-backup}"

if [[ ! -d "$NEW_DIST" ]]; then
  echo "FAILED: new dist missing: $NEW_DIST" >&2
  exit 1
fi
if [[ ! -f "$NEW_DIST/index.html" ]]; then
  echo "FAILED: new dist has no index.html: $NEW_DIST" >&2
  exit 1
fi

# Resolve to absolute paths so the LIVE symlink target is stable regardless of cwd.
LIVE_DIST="$(cd "$(dirname "$LIVE_DIST")" && pwd)/$(basename "$LIVE_DIST")"
NEW_DIST="$(cd "$NEW_DIST" && pwd)"
LIVE_PARENT="$(dirname "$LIVE_DIST")"
LIVE_BASE="$(basename "$LIVE_DIST")"
RELEASES_DIR="${LIVE_PARENT}/${LIVE_BASE}-releases"
RELEASE_ID="$(date -u +%Y%m%d%H%M%S)-$$"
RELEASE_DIR="${RELEASES_DIR}/${RELEASE_ID}"

mkdir -p "$NEW_DIST/assets"
mkdir -p "$RELEASES_DIR"

# Pure asset snapshot for the *next* grace window (before overlay).
# Written to .next so a failed deploy can leave PREV_ASSETS untouched.
rm -rf "$PREV_ASSETS_NEXT"
mkdir -p "$PREV_ASSETS_NEXT"
if compgen -G "$NEW_DIST/assets/*" > /dev/null; then
  cp -a "$NEW_DIST/assets/." "$PREV_ASSETS_NEXT/"
fi

# Overlay previous generation's hashed files (never replace newer hashes).
GRACE_COPIED=0
if [[ -d "$PREV_ASSETS" ]]; then
  shopt -s nullglob
  for src in "$PREV_ASSETS"/*; do
    [[ -f "$src" ]] || continue
    name="$(basename "$src")"
    dest="$NEW_DIST/assets/$name"
    if [[ -e "$dest" ]]; then
      continue
    fi
    cp -a "$src" "$dest"
    GRACE_COPIED=$((GRACE_COPIED + 1))
  done
  shopt -u nullglob
  echo "    Asset grace: retained ${GRACE_COPIED} prior hashed file(s) from ${PREV_ASSETS}"
else
  echo "    Asset grace: no prior asset dir (${PREV_ASSETS}) — first install or cold start"
fi

# Stage complete tree as a new release directory (never mutate the live tree).
rm -rf "$RELEASE_DIR"
mv "$NEW_DIST" "$RELEASE_DIR"

TMP_LINK="${LIVE_PARENT}/.${LIVE_BASE}.newlink.$$"
cleanup_tmp_link() {
  rm -f "$TMP_LINK" 2>/dev/null || true
}
trap cleanup_tmp_link EXIT

# Publish LIVE_DIST as a symlink to TARGET. When LIVE is still a plain directory
# (first migration), exchange it with the new symlink atomically when the kernel
# supports renameat2(RENAME_EXCHANGE) so nginx never observes a missing path.
publish_symlink() {
  local target="$1"
  ln -sfn "$target" "$TMP_LINK"
  if [[ -e "$LIVE_DIST" && ! -L "$LIVE_DIST" ]]; then
    local legacy="${RELEASES_DIR}/legacy-pre-symlink-$$"
    if python3 - "$LIVE_DIST" "$TMP_LINK" "$legacy" <<'PY'
import ctypes, os, sys

live, tmp_link, legacy = sys.argv[1], sys.argv[2], sys.argv[3]
AT_FDCWD = -100
RENAME_EXCHANGE = 2
libc = ctypes.CDLL("libc.so.6", use_errno=True)
# int renameat2(int olddirfd, const char *oldpath, int newdirfd, const char *newpath, unsigned int flags);
libc.renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
rc = libc.renameat2(
    AT_FDCWD, tmp_link.encode(), AT_FDCWD, live.encode(), RENAME_EXCHANGE
)
if rc != 0:
    sys.exit(1)
# After exchange: live is the symlink; tmp_link holds the old plain directory.
os.rename(tmp_link, legacy)
PY
    then
      echo "    Migrated plain ${LIVE_DIST} → symlink via atomic exchange (legacy retained under releases)"
      return 0
    fi
    # Fallback when renameat2 is unavailable: relocate then publish as fast as possible.
    mv "$LIVE_DIST" "$legacy"
    mv -Tf "$TMP_LINK" "$LIVE_DIST"
    echo "    Migrated plain ${LIVE_DIST} → ${legacy} (symlink-published; brief rename window)"
    return 0
  fi
  # LIVE missing or already a symlink: atomic replace via temp link rename.
  mv -Tf "$TMP_LINK" "$LIVE_DIST"
}

publish_symlink "$RELEASE_DIR"
trap - EXIT
cleanup_tmp_link

# Keep the newest 3 releases, but never delete the live symlink target or the
# rollback backup target (failed deploys must still be able to restore).
if command -v python3 >/dev/null 2>&1; then
  python3 - "$RELEASES_DIR" "$RELEASE_DIR" "$LIVE_DIST" "$DIST_BACKUP" <<'PY'
import os, shutil, sys

releases_dir, keep, live_dist, dist_backup = sys.argv[1:5]
protected = {os.path.abspath(keep)}

def add_protected(path: str) -> None:
    if not path:
        return
    try:
        if os.path.lexists(path):
            protected.add(os.path.abspath(path))
        if os.path.exists(path):
            protected.add(os.path.abspath(os.path.realpath(path)))
    except OSError:
        pass

add_protected(live_dist)
add_protected(dist_backup)

entries = []
for name in os.listdir(releases_dir):
    path = os.path.join(releases_dir, name)
    if os.path.isdir(path):
        entries.append((os.path.getmtime(path), path))
entries.sort(reverse=True)

for _, path in entries[3:]:
    abspath = os.path.abspath(path)
    if abspath in protected:
        continue
    # Also skip if this release is an ancestor of a protected realpath.
    skip = False
    for p in protected:
        try:
            if os.path.commonpath([abspath, p]) == abspath:
                skip = True
                break
        except ValueError:
            continue
    if skip:
        continue
    shutil.rmtree(path, ignore_errors=True)
PY
fi

echo "    Frontend dist installed with one-generation asset grace → ${LIVE_DIST} -> ${RELEASE_DIR}"
echo "    Deferred PREV_ASSETS promote: ${PREV_ASSETS_NEXT} (deploy.sh promotes after success)"
