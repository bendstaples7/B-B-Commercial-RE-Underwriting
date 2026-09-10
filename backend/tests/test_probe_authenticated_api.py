"""Unit tests for scripts/probe_authenticated_api.py canary helper."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts" / "probe_authenticated_api.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("probe_authenticated_api", PROBE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_probe_skips_without_creds_exits_78(monkeypatch, capsys):
    probe = _load_probe()
    monkeypatch.delenv("SMOKE_TEST_EMAIL", raising=False)
    monkeypatch.delenv("SMOKE_TEST_PASSWORD", raising=False)
    rc = probe.main(["--base-url", "https://example.test", "--skip-if-no-creds"])
    assert rc == 78
    assert "skipping" in capsys.readouterr().out.lower()


def test_probe_preserves_password_whitespace(monkeypatch):
    probe = _load_probe()
    monkeypatch.setenv("SMOKE_TEST_EMAIL", "smoke@example.com")
    monkeypatch.setenv("SMOKE_TEST_PASSWORD", "  secret  ")

    seen: dict[str, str] = {}

    def fake_login(base_url, email, password, *, timeout):
        seen["password"] = password
        return "t-test"

    monkeypatch.setattr(probe, "login", fake_login)
    monkeypatch.setattr(
        probe,
        "probe_path",
        lambda *a, **k: None,
    )
    rc = probe.main(["--base-url", "https://example.test"])
    assert rc == 0
    assert seen["password"] == "  secret  "


def test_probe_channel_roi_success(monkeypatch, capsys):
    probe = _load_probe()
    monkeypatch.setenv("SMOKE_TEST_EMAIL", "smoke@example.com")
    monkeypatch.setenv("SMOKE_TEST_PASSWORD", "secret")

    calls: list[tuple[str, str]] = []

    def fake_request(method, url, token=None, body=None, timeout=30.0):
        calls.append((method, url))
        if url.endswith("/api/auth/login"):
            return 200, {"session_token": "t-test"}
        if url.endswith("/api/marketing/channel-roi"):
            assert token == "t-test"
            return 200, {"campaigns": [], "totals": {}}
        return 500, {"error": "unexpected"}

    monkeypatch.setattr(probe, "_request", fake_request)
    rc = probe.main(["--base-url", "https://example.test", "--timeout", "5"])
    assert rc == 0
    assert any(u.endswith("/api/marketing/channel-roi") for _, u in calls)
    out = capsys.readouterr().out
    assert "Authenticated API probe passed" in out


def test_probe_fails_on_non_200(monkeypatch):
    probe = _load_probe()
    monkeypatch.setenv("SMOKE_TEST_EMAIL", "smoke@example.com")
    monkeypatch.setenv("SMOKE_TEST_PASSWORD", "secret")

    def fake_request(method, url, token=None, body=None, timeout=30.0):
        if url.endswith("/api/auth/login"):
            return 200, {"session_token": "t-test"}
        return 503, {"error": "unavailable"}

    monkeypatch.setattr(probe, "_request", fake_request)
    with pytest.raises(SystemExit) as exc:
        probe.main(["--base-url", "https://example.test"])
    assert "503" in str(exc.value)


def test_login_accepts_session_token(monkeypatch):
    probe = _load_probe()

    def fake_request(method, url, token=None, body=None, timeout=30.0):
        return 200, {"session_token": "sess-abc", "email": "x@y.z"}

    monkeypatch.setattr(probe, "_request", fake_request)
    assert probe.login("https://example.test", "a", "b", timeout=5) == "sess-abc"
