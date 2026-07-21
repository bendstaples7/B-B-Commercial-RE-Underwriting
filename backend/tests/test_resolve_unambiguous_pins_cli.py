"""Guards for resolve_unambiguous_pins --apply lock-safe timeout."""
from __future__ import annotations

import types

from scripts.resolve_unambiguous_pins import apply_timeout_supported


def test_apply_timeout_supported_requires_sigalrm(monkeypatch):
    import scripts.resolve_unambiguous_pins as mod

    monkeypatch.setattr(mod, "signal", types.SimpleNamespace())
    assert apply_timeout_supported() is False

    monkeypatch.setattr(
        mod,
        "signal",
        types.SimpleNamespace(SIGALRM=14, signal=lambda *a, **k: None, alarm=lambda *a: None),
    )
    assert apply_timeout_supported() is True
