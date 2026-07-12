"""Import IRS Exempt Organizations Business Master File (EO BMF) CSVs.

Downloads the public IRS zip (or reads a local CSV) and loads rows into
``irs_eo_organizations``. Prefer filtering to Illinois for this portfolio.

Usage (from backend/)::

    python scripts/import_irs_eo_bmf.py --dry-run
    python scripts/import_irs_eo_bmf.py --apply
    python scripts/import_irs_eo_bmf.py --apply --states IL
    python scripts/import_irs_eo_bmf.py --apply --csv path/to/eo.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("import_irs_eo_bmf")

# Public IRS EO BMF extract (region CSVs inside zip).
IRS_EO_ZIP_URL = "https://www.irs.gov/pub/epostcard/data-download-eo.zip"
DEFAULT_STATES = frozenset({"IL"})
BATCH_SIZE = 1000


def _open_csv_streams(cache_dir: Path, csv_path: Optional[Path], force: bool):
    """Yield (source_name, text_stream) one CSV at a time (avoids holding all EO files)."""
    if csv_path is not None:
        text = csv_path.read_text(encoding="utf-8", errors="replace")
        yield csv_path.name, io.StringIO(text)
        return

    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "data-download-eo.zip"
    if force or not zip_path.exists():
        logger.info("Downloading IRS EO BMF zip…")
        with urlopen(IRS_EO_ZIP_URL, timeout=120) as resp:
            zip_path.write_bytes(resp.read())
        logger.info("Saved %s (%d bytes)", zip_path, zip_path.stat().st_size)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in sorted(zf.namelist()):
            if not name.lower().endswith(".csv"):
                continue
            raw = zf.read(name).decode("utf-8", errors="replace")
            yield name, io.StringIO(raw)


def _iter_rows(streams, states: frozenset[str]):
    for source_name, handle in streams:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            logger.warning("Skipping empty CSV %s", source_name)
            continue
        for row in reader:
            state = (row.get("STATE") or row.get("state") or "").strip().upper()
            if states and state not in states:
                continue
            yield {
                "ein": row.get("EIN") or row.get("ein") or "",
                "name": row.get("NAME") or row.get("name") or "",
                "city": row.get("CITY") or row.get("city") or None,
                "state": state or None,
                "ntee_cd": row.get("NTEE_CD") or row.get("ntee_cd") or None,
                "subsection": row.get("SUBSECTION") or row.get("subsection") or None,
                "status": row.get("STATUS") or row.get("status") or None,
            }


def import_rows(*, dry_run: bool, states: frozenset[str], streams) -> dict:
    from app import db
    from app.services.entity_lookup.irs_eo import upsert_eo_row

    now = datetime.utcnow()
    seen = 0
    loaded = 0
    skipped = 0
    for row in _iter_rows(streams, states):
        seen += 1
        if not (row["ein"] and row["name"]):
            skipped += 1
            continue
        if dry_run:
            loaded += 1
            continue
        try:
            upsert_eo_row(
                ein=row["ein"],
                name=row["name"],
                city=row["city"],
                state=row["state"],
                ntee_cd=row["ntee_cd"],
                subsection=row["subsection"],
                status=row["status"],
                imported_at=now,
            )
            loaded += 1
        except ValueError:
            skipped += 1
            continue
        if loaded % BATCH_SIZE == 0:
            db.session.commit()
            logger.info("Committed %d rows…", loaded)

    if not dry_run:
        db.session.commit()
    return {"seen": seen, "loaded": loaded, "skipped": skipped, "dry_run": dry_run}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default=str(_BACKEND / "data" / "irs_eo_bmf"),
        help="Directory for downloaded IRS zip",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional local CSV path (skips download)",
    )
    parser.add_argument(
        "--states",
        default="IL",
        help="Comma-separated state filter (default: IL). Use ALL for no filter.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download IRS zip even if cached",
    )
    args = parser.parse_args()

    if args.states.strip().upper() == "ALL":
        states: frozenset[str] = frozenset()
    else:
        states = frozenset(
            s.strip().upper() for s in args.states.split(",") if s.strip()
        ) or DEFAULT_STATES

    csv_path = Path(args.csv) if args.csv else None
    streams = _open_csv_streams(Path(args.cache_dir), csv_path, args.force_download)

    from app import create_app
    app = create_app()
    with app.app_context():
        result = import_rows(
            dry_run=args.dry_run,
            states=states,
            streams=streams,
        )
        logger.info("Result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
