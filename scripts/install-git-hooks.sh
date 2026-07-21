#!/usr/bin/env bash
# Point this clone at the versioned hooks in .githooks/
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit 2>/dev/null || true
echo "core.hooksPath=$(git config --get core.hooksPath)"
echo "Git hooks installed. Pre-commit is slim (mapped tests); CI owns the full suite."
