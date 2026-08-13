#!/usr/bin/env python3
"""Emit normalized SPA /assets/ references from index.html script/link attrs."""
from __future__ import annotations

import sys
from html.parser import HTMLParser


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"script", "link"}:
            return
        attr_name = "src" if tag == "script" else "href"
        values = dict(attrs)
        value = values.get(attr_name)
        if not value:
            return
        ref = value.split("?", 1)[0].split("#", 1)[0]
        if ref.startswith("./assets/"):
            ref = ref[1:]
        elif ref.startswith("assets/"):
            ref = f"/{ref}"
        if ref.startswith("/assets/"):
            self.refs.add(ref)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: spa_asset_refs.py INDEX_HTML", file=sys.stderr)
        return 2
    parser = AssetParser()
    with open(sys.argv[1], encoding="utf-8") as fh:
        parser.feed(fh.read())
    for ref in sorted(parser.refs):
        print(ref)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
