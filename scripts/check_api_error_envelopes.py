#!/usr/bin/env python3
"""Fail CI when shared API error envelopes are not toast-unwrapped on the frontend.

Controllers often return ``{"error": "<wrapper>", "message": "<real reason>"}``.
If ``<wrapper>`` is missing from ``frontend/src/services/apiErrorEnvelopes.json``,
the UI toasts the useless wrapper label (see Ready-to-Mail "Mail queue error").

This check only scans shared error-handler modules that intentionally use fixed
envelope labels (not every domain-specific ``error`` + ``message`` pair).

Usage:
    python scripts/check_api_error_envelopes.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVELOPES_PATH = ROOT / 'frontend' / 'src' / 'services' / 'apiErrorEnvelopes.json'
CONTROLLERS_DIR = ROOT / 'backend' / 'app' / 'controllers'

# Shared handlers that wrap exception detail in a fixed ``error`` label + ``message``.
HANDLER_FILES = (
    CONTROLLERS_DIR / 'mail_api_errors.py',
    CONTROLLERS_DIR / 'decorators.py',
)

# jsonify({'error': 'Mail queue error', 'message': ...}) and close variants
# Dynamic HTTPException wrappers (must use fixed "HTTP error", not e.name).
DYNAMIC_HTTP_ENVELOPE = re.compile(
    r"""['"]error['"]\s*:\s*getattr\(\s*\w+\s*,\s*['"]name['"]""",
)

ENVELOPE_PATTERN = re.compile(
    r"""['\"]error['\"]\s*:\s*['\"]([^'\"]+)['\"]"""
    r"""[^}]{0,200}"""
    r"""['\"]message['\"]\s*:""",
    re.DOTALL,
)


def load_allowlist() -> set[str]:
    data = json.loads(ENVELOPES_PATH.read_text(encoding='utf-8'))
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise SystemExit(f'{ENVELOPES_PATH} must be a JSON array of strings')
    return set(data)


def find_handler_envelopes() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in HANDLER_FILES:
        if not path.is_file():
            raise SystemExit(f'Missing expected error-handler file: {path}')
        text = path.read_text(encoding='utf-8')
        labels = sorted({m.group(1) for m in ENVELOPE_PATTERN.finditer(text)})
        if labels:
            found[str(path.relative_to(ROOT))] = labels
    return found


def main() -> int:
    allowlist = load_allowlist()
    backend = find_handler_envelopes()
    missing: list[tuple[str, str]] = []
    for path, labels in backend.items():
        for label in labels:
            if label not in allowlist:
                missing.append((path, label))

    if missing:
        print('API error envelopes used with `message` but missing from')
        print(f'  {ENVELOPES_PATH.relative_to(ROOT)}')
        print()
        for path, label in missing:
            print(f'  - {label!r}  ({path})')
        print()
        print('Add the label to apiErrorEnvelopes.json so toasts show `message`.')
        return 1

    dynamic_hits: list[str] = []
    for path in HANDLER_FILES:
        text = path.read_text(encoding='utf-8')
        if DYNAMIC_HTTP_ENVELOPE.search(text):
            dynamic_hits.append(str(path.relative_to(ROOT)))
    if dynamic_hits:
        print('Dynamic HTTP error envelopes still use getattr(..., "name"):')
        for path in dynamic_hits:
            print(f'  - {path}')
        print('Use a fixed label like "HTTP error" so toasts can unwrap `message`.')
        return 1

    all_labels = sorted({label for labels in backend.values() for label in labels})
    print(f'OK: {len(all_labels)} shared envelope label(s) covered by allowlist')
    for label in all_labels:
        print(f'  - {label}')
    unused = sorted(allowlist - set(all_labels))
    if unused:
        print('Allowlist also includes (used outside scanned handlers or legacy):')
        for label in unused:
            print(f'  - {label}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
