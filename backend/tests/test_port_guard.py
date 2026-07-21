"""Tests for local Flask port occupancy guard."""
import pytest

from port_guard import (
    PortProbeError,
    assert_port_free,
    list_listening_pids,
)


def test_list_listening_pids_returns_ints_for_flask_port():
    """When something listens on 5000, PIDs are positive ints (or empty if free)."""
    pids = list_listening_pids(5000)
    assert isinstance(pids, list)
    assert all(isinstance(p, int) and p > 0 for p in pids)


def test_list_listening_pids_lenient_on_probe_failure(monkeypatch):
    def _boom(port):
        raise PortProbeError("no probe")

    monkeypatch.setattr("port_guard._probe_listening_pids", _boom)
    assert list_listening_pids(5000) == []


def test_assert_port_free_passes_when_ignored(monkeypatch):
    monkeypatch.setattr("port_guard._probe_listening_pids", lambda port: [111, 222])
    # Ignoring all foreign PIDs should not exit.
    assert_port_free(5000, ignore_pids={111, 222})


def test_assert_port_free_exits_when_occupied(monkeypatch):
    monkeypatch.setattr("port_guard._probe_listening_pids", lambda port: [4242])
    monkeypatch.setattr("port_guard.describe_pid", lambda pid: "fake-flask")
    with pytest.raises(SystemExit) as exc:
        assert_port_free(5000)
    message = str(exc.value)
    assert "PORT 5000 ALREADY IN USE" in message
    assert "4242" in message
    assert "python dev.py" in message


def test_assert_port_free_fails_closed_on_probe_error(monkeypatch):
    def _boom(port):
        raise PortProbeError("netstat missing")

    monkeypatch.setattr("port_guard._probe_listening_pids", _boom)
    monkeypatch.delenv("PORT_GUARD_ALLOW_FAIL_OPEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        assert_port_free(5000)
    assert "STATE UNKNOWN" in str(exc.value)


def test_assert_port_free_fail_open_escape_hatch(monkeypatch):
    def _boom(port):
        raise PortProbeError("netstat missing")

    monkeypatch.setattr("port_guard._probe_listening_pids", _boom)
    monkeypatch.setenv("PORT_GUARD_ALLOW_FAIL_OPEN", "1")
    # Should not raise when the escape hatch is set.
    assert_port_free(5000)
