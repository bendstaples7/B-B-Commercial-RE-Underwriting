"""Contract checks for the Windows production DB sync helper."""
from pathlib import Path


def _script_text() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "scripts" / "sync-from-prod.ps1").read_text(encoding="utf-8")


def test_scheduled_task_wrapper_path_matches_current_checkout():
    text = _script_text()

    assert '$launcherArgs = "//B //Nologo `"$launcher`""' in text
    assert "($existing.Actions[0].Arguments -eq $launcherArgs)" in text
    assert "-Argument $launcherArgs" in text
    assert "-like '*sync-from-prod-hidden.vbs*'" not in text


def test_start_process_path_arguments_are_quoted():
    text = _script_text()

    assert '"-i", "`"$VPS_SSH_KEY`""' in text
    assert '"-o", "`"UserKnownHostsFile=$VPS_KNOWN_HOSTS_FILE`""' in text
    assert '"`"$DUMP_FILE`""' in text
