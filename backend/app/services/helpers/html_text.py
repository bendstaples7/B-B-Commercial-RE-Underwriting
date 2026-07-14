"""HTML → plain text helpers for HubSpot and other CRM bodies."""
from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser

_UNTERMINATED_TAG_RE = re.compile(r'<[a-zA-Z/][^>]*$')


class _HTMLToTextParser(HTMLParser):
    """Convert HTML to plain text, correctly handling quoted attributes."""

    _BREAK_TAGS = frozenset({
        'br', 'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in self._BREAK_TAGS:
            self._parts.append('\n' if tag.lower() == 'br' else ' ')

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BREAK_TAGS and tag.lower() != 'br':
            self._parts.append(' ')

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        return ''.join(self._parts)


def strip_html_tags(raw_html: str | None, *, preserve_newlines: bool = False) -> str:
    """Strip HTML tags from a string and return plain text.

    Uses an HTML parser so attributes containing ``>`` cannot leak into the
    result. ``<br>`` (with optional attributes) becomes a newline; other
    block closers become spaces. Entity-encoded markup is unescaped and
    re-stripped until stable. Returns '' for falsy input.
    """
    if not raw_html:
        return ''
    text = str(raw_html)
    for _ in range(3):
        parser = _HTMLToTextParser()
        try:
            parser.feed(text)
            parser.close()
            text = parser.get_text()
        except Exception:
            # Extremely malformed input — fall back to conservative regex
            text = re.sub(r'(?i)<\s*br\b[^>]*>', '\n', text)
            text = re.sub(r'(?i)</\s*(p|div|li|tr|h[1-6])\s*>', ' ', text)
            text = re.sub(r'<[^>]+>', '', text)
        text = _UNTERMINATED_TAG_RE.sub('', text)
        unescaped = html_lib.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    if preserve_newlines:
        text = re.sub(r'[^\S\n]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    return re.sub(r'\s+', ' ', text).strip()
