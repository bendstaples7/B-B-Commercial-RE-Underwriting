"""Turn database integrity errors into a message a person can read."""
from __future__ import annotations

import re

_QUOTED_RULE = re.compile(
    r"""(?:unique constraint|index)\s+["']([A-Za-z0-9_.]+)["']""",
    re.IGNORECASE,
)
_UQ_NAME = re.compile(r"\b(uq_[a-z0-9_]+)\b", re.IGNORECASE)
_UNIQUE_VIOLATION_TEXT = re.compile(
    r"\b(?:unique constraint|duplicate key|unique constraint failed)\b",
    re.IGNORECASE,
)


def _integrity_error_text(exc: BaseException) -> str:
    orig = getattr(exc, "orig", None)
    return " ".join(
        part for part in (str(exc), str(orig) if orig is not None else "") if part
    )


def integrity_constraint_name(exc: BaseException) -> str | None:
    """Return the unique index or constraint name, when the driver includes one."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None) if orig is not None else None
    if diag is not None:
        name = getattr(diag, "constraint_name", None)
        if name:
            return str(name)
    text = _integrity_error_text(exc)
    quoted = _QUOTED_RULE.search(text)
    if quoted:
        return quoted.group(1)
    named = _UQ_NAME.search(text)
    if named:
        return named.group(1)
    return None


def is_unique_integrity_error(exc: BaseException) -> bool:
    """Return True when the driver text or SQLSTATE proves a unique violation."""
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if str(sqlstate) == "23505":
        return True
    return bool(_UNIQUE_VIOLATION_TEXT.search(_integrity_error_text(exc)))


def integrity_error_message(exc: BaseException, *, action: str) -> str:
    """Sentence for the screen. Includes the index name when we have it."""
    name = integrity_constraint_name(exc)
    if name:
        return f"{action} was blocked by database rule {name}."
    if is_unique_integrity_error(exc):
        return f"{action} was blocked by a database uniqueness rule."
    return f"{action} was blocked by a database integrity rule."
