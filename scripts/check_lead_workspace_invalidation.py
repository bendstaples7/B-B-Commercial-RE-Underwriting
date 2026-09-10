#!/usr/bin/env python3
"""Fail CI when mail mutations forget lead-workspace invalidation.

Mail enqueue / remove / send change open tasks and mail chips on the command
center. Those paths must *call* ``afterLeadWorkspaceMutation(`` (or
``invalidateAllCommandCenters(`` for full-batch send) so the 60s workspace
stale window cannot leave cancelled rematch rows completable in the UI.

Imports alone must not satisfy this contract — match call sites (token + '(').

Usage:
    python scripts/check_lead_workspace_invalidation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend' / 'src'

# Each file must contain at least one of the required *call* tokens.
REQUIRED: dict[str, tuple[str, ...]] = {
    'components/MailQueueStagedTable.tsx': (
        'afterLeadWorkspaceMutation(',
    ),
    'components/queueBulkActions.tsx': (
        'afterLeadWorkspaceMutation(',
    ),
    'components/ReadyToMailQueue.tsx': (
        'afterLeadWorkspaceMutation(',
    ),
    'components/MailBatchSummary.tsx': (
        'afterLeadWorkspaceMutation(',
        'invalidateAllCommandCenters(',
    ),
}


def main() -> int:
    failures: list[str] = []
    for rel, tokens in REQUIRED.items():
        path = FRONTEND / rel
        if not path.is_file():
            failures.append(f'missing file: {rel}')
            continue
        text = path.read_text(encoding='utf-8')
        if not any(token in text for token in tokens):
            failures.append(
                f'{rel} must call one of: {", ".join(tokens)}'
            )

    if failures:
        print('Lead-workspace invalidation contract failed:')
        print()
        for line in failures:
            print(f'  - {line}')
        print()
        print(
            'Mail mutations that change tasks/RA/mail chips must refresh '
            'command-center via afterLeadWorkspaceMutation(…) '
            '(see frontend/src/utils/afterCommandCenterMutation.ts).'
        )
        return 1

    print(f'OK — {len(REQUIRED)} mail mutation paths refresh lead workspaces.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
