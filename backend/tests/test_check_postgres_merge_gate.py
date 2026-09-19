"""Regression tests for the static Postgres merge-gate guard."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'check_postgres_merge_gate.py'

VALID_WORKFLOW = """name: App CI

on:
  pull_request:
    branches: [main]

jobs:
  postgres-merge-gate:
    runs-on: ubuntu-latest
    steps:
      - run: |
          flask db upgrade
          POSTGRES_MERGE_GATE=1 pytest tests/test_merge_postgres_gate.py --junitxml=/tmp/merge-gate.xml
          echo postgresql://

  ci-success:
    if: always()
    needs:
      - postgres-merge-gate
    runs-on: ubuntu-latest
    steps:
      - run: |
          gate="${{ needs.postgres-merge-gate.result }}"
          if [ "$gate" != "success" ]; then
            echo "A skip does not count"
          fi
"""

VALID_GATE_TEST = """def test_combine_keeps_pin_and_selected_person():
    response = client.post('/api/leads/1/merge-into/2')
    assert response.status_code == 200
    people_names = ['Grace Hopper']
    county_assessor_pin = pin
    POSTGRES_MERGE_GATE = '1'
    assert 'uq_leads_owner_normalized_street'
    assert 'uq_leads_owner_assessor_pin'
    assert saved.county_assessor_pin == pin
    assert saved.owner_first_name == 'Grace'
    assert saved.owner_last_name == 'Hopper'


def test_combine_aligns_street_for_the_same_owner():
    assert saved.property_street == '2834 N Drake Rear'
"""


def _load_gate_module():
    spec = importlib.util.spec_from_file_location('check_postgres_merge_gate', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _configure_files(tmp_path, workflow=VALID_WORKFLOW, test_src=VALID_GATE_TEST):
    module = _load_gate_module()
    workflow_path = tmp_path / 'ci.yml'
    test_path = tmp_path / 'test_merge_postgres_gate.py'
    workflow_path.write_text(workflow)
    test_path.write_text(test_src)
    module.WORKFLOW = workflow_path
    module.GATE_TEST = test_path
    return module


def test_accepts_valid_gate_fixture(tmp_path, capsys):
    module = _configure_files(tmp_path)

    assert module.main() == 0
    assert 'Postgres merge gate is required before deploy.' in capsys.readouterr().out


def test_rejects_continue_on_error_in_gate_job(tmp_path, capsys):
    workflow = VALID_WORKFLOW.replace(
        '  postgres-merge-gate:\n',
        '  postgres-merge-gate:\n    continue-on-error: true\n',
    )
    module = _configure_files(tmp_path, workflow=workflow)

    assert module.main() == 1
    assert 'continue-on-error' in capsys.readouterr().err


def test_rejects_workflow_path_filters(tmp_path, capsys):
    workflow = VALID_WORKFLOW.replace(
        '  pull_request:\n    branches: [main]\n',
        '  pull_request:\n    branches: [main]\n    paths: ["backend/**"]\n',
    )
    module = _configure_files(tmp_path, workflow=workflow)

    assert module.main() == 1
    assert 'path-filtered' in capsys.readouterr().err


def test_rejects_missing_named_regression_case(tmp_path, capsys):
    test_src = VALID_GATE_TEST.replace(
        'def test_combine_keeps_pin_and_selected_person',
        'def test_removed_pin_person_regression',
    )
    module = _configure_files(tmp_path, test_src=test_src)

    assert module.main() == 1
    assert 'PIN and selected-person combine regression' in capsys.readouterr().err
