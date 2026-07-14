"""HTML → plain text helpers for HubSpot and other CRM bodies."""
from __future__ import annotations

import html as html_lib
import re

_HTML_TAG_RE = re.compile(r'<[^>]+>')


def strip_html_tags(raw_html: str | None) -> str:
    """Strip HTML tags from a string and return collapsed plain text.

    Block-level closers and <br> are turned into spaces so adjacent words don't
    run together, remaining tags are removed, HTML entities are unescaped, and
    runs of whitespace are collapsed. Returns '' for falsy input.

    Unescape + strip are repeated so entity-encoded markup (``&lt;b&gt;``)
    cannot survive as visible tags after a single pass.
    """
    if not raw_html:
        return ''
    text = str(raw_html)
    for _ in range(3):
        text = re.sub(r'(?i)<\s*br\s*/?>', ' ', text)
        text = re.sub(r'(?i)</\s*(p|div|li|tr|h[1-6])\s*>', ' ', text)
        text = _HTML_TAG_RE.sub('', text)
        # Truncated CRM bodies may leave an unterminated '<' fragment
        text = re.sub(r'<[^>]*$', '', text)
        unescaped = html_lib.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = re.sub(r'\s+', ' ', text).strip()
    return text
