#!/usr/bin/env python
"""Download and load free Illinois SOS LLC Transparency Act bulk dumps.

Usage (from backend/)::

    python scripts/import_il_sos_llc_bulk.py --dry-run
    python scripts/import_il_sos_llc_bulk.py --apply
    python scripts/import_il_sos_llc_bulk.py --apply --force-download
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("import_il_sos_llc_bulk")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default=str(_BACKEND / "data" / "il_sos_bulk"),
        help="Directory for downloaded zips (default: backend/data/il_sos_bulk)",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download zips even if cached",
    )
    parser.add_argument(
        "--prefer-github",
        action="store_true",
        help=(
            "Use free GitHub community CSV zip derived from ILSOS Transparency Act "
            "dumps (fallback when ilsos.gov is unreachable)"
        ),
    )
    args = parser.parse_args()

    from app import create_app
    from app.services.entity_lookup.ilsos_import_service import IlSosBulkImportService

    app = create_app()
    with app.app_context():
        result = IlSosBulkImportService().import_all(
            Path(args.cache_dir),
            dry_run=args.dry_run,
            force_download=args.force_download,
            prefer_github=args.prefer_github,
        )
        logger.info("Result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
