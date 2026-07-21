"""Tests for process build_id / source_stale identity."""
from app.runtime_identity import (
    compute_source_fingerprint,
    get_runtime_identity,
    init_runtime_identity,
    is_source_stale,
    runtime_identity_exposed,
)


def test_runtime_identity_includes_build_id_and_flags():
    init_runtime_identity()
    payload = get_runtime_identity()
    assert payload["build_id"]
    assert payload["pid"] > 0
    assert payload["started_at"].endswith("Z")
    assert payload["source_stale"] is False
    assert isinstance(compute_source_fingerprint(), str)


def test_health_includes_runtime_identity(client):
    response = client.get("/api/health")
    assert response.status_code in (200, 503)
    data = response.get_json()
    assert "build_id" in data
    assert data["build_id"]
    assert "source_stale" in data
    assert data["source_stale"] is False
    assert "started_at" in data
    assert "pid" in data


def test_runtime_health_endpoint_is_cheap_and_public(client):
    response = client.get("/api/health/runtime")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["build_id"]
    assert data["source_stale"] is False
    # Cheap probe must not run the heavy dependency checks.
    assert "checks" not in data


def test_identity_hidden_in_production(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    assert runtime_identity_exposed() is False
    assert get_runtime_identity() == {}


def test_identity_exposed_outside_production(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    assert runtime_identity_exposed() is True
    assert "build_id" in get_runtime_identity()


def test_source_fingerprint_is_source_mtime_hash():
    # Stale comparison must not include the git SHA (checkout must not read
    # as a stale process) — fingerprint hashes loaded source path mtimes.
    fingerprint = compute_source_fingerprint()
    assert len(fingerprint) == 64
    int(fingerprint, 16)


def test_source_stale_when_loaded_file_modified_after_start(monkeypatch):
    monkeypatch.setattr("app.runtime_identity._STARTED_AT_NS", 1_000)
    monkeypatch.setattr(
        "app.runtime_identity._loaded_backend_mtimes",
        lambda: {"loaded.py": 1_001},
    )

    assert is_source_stale() is True


def test_source_not_stale_for_loaded_files_older_than_start(monkeypatch):
    monkeypatch.setattr("app.runtime_identity._STARTED_AT_NS", 1_000)
    monkeypatch.setattr(
        "app.runtime_identity._loaded_backend_mtimes",
        lambda: {"lazy_old.py": 999},
    )

    assert is_source_stale() is False


def test_source_not_stale_when_no_loaded_backend_files(monkeypatch):
    monkeypatch.setattr("app.runtime_identity._loaded_backend_mtimes", lambda: {})
    assert is_source_stale() is False
