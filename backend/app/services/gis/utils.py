"""Shared helpers for GIS connectors.

Small, dependency-free utilities used by more than one county connector.
Keeping a single implementation here avoids the LIKE-escaping logic drifting
between connectors.
"""

from __future__ import annotations


def escape_like(value: str) -> str:
    r"""Escape SQL ``LIKE`` wildcards so user input is matched literally.

    Escapes the escape character first, then the ``%`` and ``_`` wildcards,
    using backslash as the escape char. Must be paired with an explicit
    ``ESCAPE '\\'`` clause in the query — the Python string literal for a
    single backslash escape char in the emitted SQL (the connectors build it
    as ``f"... ESCAPE '\\'"``) — so ``%`` / ``_`` in an address can't act as
    wildcards (wrong matches) and a stray ``\`` can't break the clause.
    """
    return (
        value.replace('\\', '\\\\')
             .replace('%', '\\%')
             .replace('_', '\\_')
    )
