"""Load Illinois SOS LLC Transparency Act bulk dumps into Postgres.

Primary source: official ilsos.gov fixed-width zips.
Free fallback when ILSOS is unreachable: community CSV zip from
https://github.com/fgregg/il-corporate-filings (derived from the same
Transparency Act dumps — still free, may be stale).
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from sqlalchemy import text

from app import db
from app.models.il_sos_llc import (
    IlSosImportRun,
    IlSosLlcAgent,
    IlSosLlcEntity,
    IlSosLlcManager,
)
from app.services.entity_lookup.ilsos_parser import (
    AGENT_SCHEMA,
    MANAGER_SCHEMA,
    MASTER_SCHEMA,
    NAME_SCHEMA,
    format_zip,
    iter_records,
    normalize_llc_name,
)
from app.services.plugins.owner_name_utils import is_entity_name

logger = logging.getLogger(__name__)

ILSOS_BASE = "https://www.ilsos.gov/data/bs"
GITHUB_LLC_ZIP = (
    "https://github.com/fgregg/il-corporate-filings/releases/download/nightly/llc.zip"
)
FILES = {
    "name": "llcallnam.zip",
    "managers": "llcallmgr.zip",
    "agent": "llcallagt.zip",
    "master": "llcallmst.zip",
}
BATCH_SIZE = 5000


def _clip(value: Optional[str], max_len: int) -> Optional[str]:
    cleaned = (value or "").strip() or None
    if cleaned is None:
        return None
    return cleaned[:max_len]


def download_url(url: str, dest: Path, *, timeout: int = 180) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s", url)
    req = Request(
        url,
        headers={"User-Agent": "B-B-RealEstateAnalyzer/1.0 (entity-resolution)"},
    )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        dest.write_bytes(resp.read())
    logger.info("Wrote %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def download_ilsos_zip(filename: str, cache_dir: Path, *, force: bool = False) -> Path:
    dest = cache_dir / filename
    if dest.exists() and not force and dest.stat().st_size > 0:
        logger.info("Using cached %s", dest)
        return dest
    return download_url(f"{ILSOS_BASE}/{filename}", dest)


def read_zip_text(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not names:
            names = zf.namelist()
        if not names:
            raise ValueError(f"No files in {zip_path}")
        with zf.open(names[0]) as fh:
            raw = fh.read()
    return raw.decode("latin-1", errors="replace")


def _iter_csv_from_zip(zip_path: Path, member: str) -> Iterable[dict[str, str]]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(member) as fh:
            text_stream = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            yield from csv.DictReader(text_stream)


def _chunked(items: Iterable, size: int) -> Iterable[list]:
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _dict_by_file_number(records: Iterable[dict], label: str) -> dict[str, dict]:
    keyed: dict[str, dict] = {}
    duplicates = 0
    for rec in records:
        file_number = (rec.get("file_number") or "").strip()
        if not file_number:
            continue
        if file_number in keyed:
            duplicates += 1
            logger.warning(
                "Duplicate IL SOS %s record for file_number=%s; keeping latest",
                label,
                file_number,
            )
        keyed[file_number] = rec
    if duplicates:
        logger.warning("IL SOS %s import saw %d duplicate file_number rows", label, duplicates)
    return keyed


class IlSosBulkImportService:
    """Download + parse + load free IL SOS LLC bulk files."""

    def import_all(
        self,
        cache_dir: Path,
        *,
        dry_run: bool = False,
        force_download: bool = False,
        prefer_github: bool = False,
    ) -> dict:
        started = datetime.utcnow()
        source = "ilsos_transparency_act"
        run = IlSosImportRun(
            source=source,
            status="running" if not dry_run else "dry_run",
            started_at=started,
            row_counts={},
        )
        if not dry_run:
            db.session.add(run)
            db.session.flush()

        try:
            name_recs, master_recs, manager_recs, agent_recs, source = (
                self._load_records(cache_dir, force_download=force_download, prefer_github=prefer_github)
            )
            run.source = source

            if dry_run:
                sample_names = []
                name_count = 0
                for rec in name_recs:
                    name_count += 1
                    if len(sample_names) < 5:
                        sample_names.append(rec.get("name"))
                manager_count = sum(1 for _ in manager_recs)
                counts = {
                    "names": name_count,
                    "masters": len(master_recs),
                    "managers": manager_count,
                    "agents": len(agent_recs),
                    "source": source,
                }
                logger.info("Parsed IL SOS records: %s", counts)
                return {
                    "dry_run": True,
                    "row_counts": counts,
                    "sample_names": sample_names,
                }

            db.session.execute(text("DELETE FROM il_sos_llc_managers"))
            db.session.execute(text("DELETE FROM il_sos_llc_agents"))
            db.session.execute(text("DELETE FROM il_sos_llc_entities"))
            db.session.flush()

            imported_at = datetime.utcnow()
            entity_keys: set[str] = set()
            name_count = 0
            entity_count = 0

            def iter_entities():
                nonlocal name_count, entity_count
                for rec in name_recs:
                    name_count += 1
                    fn = (rec.get("file_number") or "").strip()
                    name = (rec.get("name") or "").strip()
                    if not fn or not name:
                        continue
                    master = master_recs.get(fn) or {}
                    entity_count += 1
                    entity_keys.add(fn[:8])
                    yield IlSosLlcEntity(
                        file_number=fn[:8],
                        name=name[:200],
                        normalized_name=normalize_llc_name(name)[:200],
                        status_code=(master.get("status_code") or None),
                        management_type=(master.get("management_type") or None),
                        juris_organized=(master.get("juris_organized") or None),
                        imported_at=imported_at,
                    )

            for batch in _chunked(iter_entities(), BATCH_SIZE):
                db.session.bulk_save_objects(batch)
                db.session.flush()

            manager_source_count = 0
            manager_count = 0

            def iter_managers():
                nonlocal manager_source_count, manager_count
                for rec in manager_recs:
                    manager_source_count += 1
                    fn = (rec.get("file_number") or "").strip()[:8]
                    if fn not in entity_keys:
                        continue
                    mm_name = (rec.get("mm_name") or "").strip()
                    if not mm_name:
                        continue
                    manager_count += 1
                    yield IlSosLlcManager(
                        file_number=fn,
                        mm_name=mm_name[:120],
                        mm_street=_clip(rec.get("mm_street"), 60),
                        mm_city=_clip(rec.get("mm_city"), 40),
                        mm_juris=_clip(rec.get("mm_juris"), 2),
                        mm_zip=format_zip(rec.get("mm_zip")),
                        mm_file_date=_clip(rec.get("mm_file_date"), 20),
                        mm_type_code=_clip(rec.get("mm_type_code"), 1),
                        is_company=is_entity_name(mm_name),
                    )

            for batch in _chunked(iter_managers(), BATCH_SIZE):
                db.session.bulk_save_objects(batch)
                db.session.flush()

            agent_count = 0

            def iter_agents():
                nonlocal agent_count
                for fn, rec in agent_recs.items():
                    key = fn[:8]
                    if key not in entity_keys:
                        continue
                    agent_name = (rec.get("agent_name") or "").strip()
                    if not agent_name:
                        continue
                    agent_count += 1
                    yield IlSosLlcAgent(
                        file_number=key,
                        agent_name=agent_name[:120],
                        agent_street=_clip(rec.get("agent_street"), 60),
                        agent_city=_clip(rec.get("agent_city"), 40),
                        agent_zip=format_zip(rec.get("agent_zip")),
                        agent_code=_clip(rec.get("agent_code"), 1),
                    )

            for batch in _chunked(iter_agents(), BATCH_SIZE):
                db.session.bulk_save_objects(batch)
                db.session.flush()

            counts = {
                "names": name_count,
                "masters": len(master_recs),
                "managers": manager_source_count,
                "agents": len(agent_recs),
                "source": source,
                "entities_loaded": entity_count,
                "managers_loaded": manager_count,
                "agents_loaded": agent_count,
            }
            logger.info("Parsed IL SOS records: %s", counts)

            run.status = "success"
            run.finished_at = datetime.utcnow()
            run.row_counts = counts
            db.session.commit()
            logger.info("IL SOS bulk import complete: %s", counts)
            return {"dry_run": False, "row_counts": counts, "import_run_id": run.id}

        except Exception as exc:
            logger.exception("IL SOS bulk import failed")
            if not dry_run:
                db.session.rollback()
                fail = IlSosImportRun(
                    source=source,
                    status="error",
                    started_at=started,
                    finished_at=datetime.utcnow(),
                    error=str(exc),
                )
                db.session.add(fail)
                db.session.commit()
            raise

    def _load_records(
        self,
        cache_dir: Path,
        *,
        force_download: bool,
        prefer_github: bool,
    ) -> tuple[Iterable[dict], dict[str, dict], Iterable[dict], dict[str, dict], str]:
        cache_dir.mkdir(parents=True, exist_ok=True)

        if prefer_github:
            return self._load_github_csv(cache_dir, force_download=force_download)

        # Prefer already-cached official zips
        official_cached = all(
            (cache_dir / fname).exists() and (cache_dir / fname).stat().st_size > 0
            for fname in FILES.values()
        )
        try:
            if official_cached and not force_download:
                return self._load_official_fixed_width(cache_dir, force_download=False)
            return self._load_official_fixed_width(cache_dir, force_download=force_download)
        except (TimeoutError, URLError, OSError, zipfile.BadZipFile, ValueError) as exc:
            logger.warning(
                "Official ILSOS download failed (%s); falling back to free GitHub CSV zip",
                exc,
            )
            return self._load_github_csv(cache_dir, force_download=True)

    def _load_official_fixed_width(
        self, cache_dir: Path, *, force_download: bool,
    ) -> tuple[Iterable[dict], dict[str, dict], Iterable[dict], dict[str, dict], str]:
        paths = {
            key: download_ilsos_zip(fname, cache_dir, force=force_download)
            for key, fname in FILES.items()
        }
        name_recs = iter_records(read_zip_text(paths["name"]), NAME_SCHEMA)
        master_recs = _dict_by_file_number(
            iter_records(read_zip_text(paths["master"]), MASTER_SCHEMA),
            "master",
        )
        manager_recs = iter_records(read_zip_text(paths["managers"]), MANAGER_SCHEMA)
        agent_recs = _dict_by_file_number(
            iter_records(read_zip_text(paths["agent"]), AGENT_SCHEMA),
            "agent",
        )
        return name_recs, master_recs, manager_recs, agent_recs, "ilsos_transparency_act"

    def _load_github_csv(
        self, cache_dir: Path, *, force_download: bool,
    ) -> tuple[Iterable[dict], dict[str, dict], Iterable[dict], dict[str, dict], str]:
        dest = cache_dir / "llc_github.zip"
        if force_download or not dest.exists() or dest.stat().st_size == 0:
            download_url(GITHUB_LLC_ZIP, dest, timeout=300)
        name_recs = _iter_csv_from_zip(dest, "llcallnam.csv")
        master_recs = _dict_by_file_number(
            _iter_csv_from_zip(dest, "llcallmst.csv"),
            "master",
        )
        manager_recs = _iter_csv_from_zip(dest, "llcallmgr.csv")
        agent_recs = _dict_by_file_number(
            _iter_csv_from_zip(dest, "llcallagt.csv"),
            "agent",
        )
        return (
            name_recs,
            master_recs,
            manager_recs,
            agent_recs,
            "ilsos_transparency_act_github_csv",
        )


def latest_successful_import() -> Optional[IlSosImportRun]:
    return (
        IlSosImportRun.query
        .filter_by(status="success")
        .order_by(IlSosImportRun.finished_at.desc())
        .first()
    )
