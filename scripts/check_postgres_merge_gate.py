#!/usr/bin/env python3
"""Fail if Combine can ship again without the Postgres unique-index gate.

The parallel pytest suite uses SQLite. Production rejects merges that violate
uq_leads_owner_normalized_street and uq_leads_owner_assessor_pin. App CI
success is what starts Deploy, and a skipped job counts as success there.
This check keeps the Postgres merge gate required.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'ci.yml'
GATE_TEST = ROOT / 'backend' / 'tests' / 'test_merge_postgres_gate.py'

REQUIRED_TEST_SNIPPETS = (
    'uq_leads_owner_normalized_street',
    'uq_leads_owner_assessor_pin',
    'merge-into',
    'people_names',
    'county_assessor_pin',
    'POSTGRES_MERGE_GATE',
    'status_code == 200',
)

REQUIRED_TEST_CASES = {
    'PIN and selected-person combine regression': (
        'def test_combine_keeps_pin_and_selected_person',
        'assert saved.county_assessor_pin == pin',
        "assert saved.owner_first_name == 'Grace'",
        "assert saved.owner_last_name == 'Hopper'",
    ),
    'same-owner street alignment regression': (
        'def test_combine_aligns_street_for_the_same_owner',
        "assert saved.property_street == '2834 N Drake Rear'",
    ),
}


def _job_block(workflow: str, job_id: str) -> str:
    lines = workflow.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f'  {job_id}:'):
            start = index
            break
    if start is None:
        raise SystemExit(f'ci.yml is missing job {job_id}')
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if (
            line.startswith('  ')
            and not line.startswith('   ')
            and line.rstrip().endswith(':')
        ):
            end = index
            break
    return ''.join(lines[start:end])


def main() -> int:
    workflow = WORKFLOW.read_text()
    if not GATE_TEST.is_file():
        print(f'Missing {GATE_TEST}', file=sys.stderr)
        return 1
    test_src = GATE_TEST.read_text()
    missing = [snippet for snippet in REQUIRED_TEST_SNIPPETS if snippet not in test_src]
    if missing:
        print(
            'Postgres merge gate test is missing required coverage: '
            + ', '.join(missing),
            file=sys.stderr,
        )
        return 1
    missing_cases = [
        name
        for name, snippets in REQUIRED_TEST_CASES.items()
        if any(snippet not in test_src for snippet in snippets)
    ]
    if missing_cases:
        print(
            'Postgres merge gate test is missing required regression cases: '
            + ', '.join(missing_cases),
            file=sys.stderr,
        )
        return 1

    trigger = workflow.split('jobs:', 1)[0]
    block = _job_block(workflow, 'postgres-merge-gate')
    problems: list[str] = []
    if 'paths:' in trigger or 'paths-ignore:' in trigger:
        problems.append('App CI workflow must not be path-filtered')
    if 'needs:' in block.split('steps:', 1)[0]:
        problems.append('postgres-merge-gate must not wait on path filters')
    header = block.split('steps:', 1)[0]
    if '\n    if:' in header or header.startswith('if:'):
        problems.append('postgres-merge-gate must not be skippable with if:')
    if 'continue-on-error:' in block:
        problems.append('postgres-merge-gate must not use continue-on-error')
    for needle in (
        'flask db upgrade',
        'tests/test_merge_postgres_gate.py',
        'POSTGRES_MERGE_GATE',
        'postgresql://',
        'junitxml',
    ):
        if needle not in block:
            problems.append(f'postgres-merge-gate job is missing {needle}')
    if 'postgres-merge-gate' not in _job_block(workflow, 'ci-success'):
        problems.append('App CI success does not require postgres-merge-gate')
    success = _job_block(workflow, 'ci-success')
    if 'needs.postgres-merge-gate.result' not in success:
        problems.append('App CI success does not read the postgres merge gate result')
    if 'A skip does not count' not in success:
        problems.append('App CI success still treats a skipped merge gate as passing')

    if problems:
        print('Postgres merge gate is not required:', file=sys.stderr)
        for problem in problems:
            print(f'  - {problem}', file=sys.stderr)
        return 1
    print('Postgres merge gate is required before deploy.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
