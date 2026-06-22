"""CI gate: deploy.sh, sudoers, and helper scripts stay in sync."""
import subprocess
import sys
from pathlib import Path


def test_deploy_contract_passes():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "validate_deploy_contract.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
