"""SQL LIKE helpers shared by service-layer searches."""

from __future__ import annotations


def escape_like_pattern(value: str) -> str:
    r"""Escape SQL ``LIKE`` metacharacters for queries using ``ESCAPE '\'``."""
    return (
        (value or '')
        .replace('\\', '\\\\')
        .replace('%', '\\%')
        .replace('_', '\\_')
    )
