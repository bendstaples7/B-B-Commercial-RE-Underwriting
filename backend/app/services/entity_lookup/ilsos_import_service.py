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
    normalize_llc_name,
    parse_records,
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


def _read_csv_from_zip(zip_path: Path, member: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(member) as fh:
            text_stream = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            return list(csv.DictReader(text_stream))


def _chunked(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


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

            counts = {
                "names": len(name_recs),
                "masters": len(master_recs),
                "managers": len(manager_recs),
                "agents": len(agent_recs),
                "source": source,
            }
            logger.info("Parsed IL SOS records: %s", counts)

            if dry_run:
                return {
                    "dry_run": True,
                    "row_counts": counts,
                    "sample_names": [r.get("name") for r in name_recs[:5]],
                }

            db.session.execute(text("DELETE FROM il_sos_llc_managers"))
            db.session.execute(text("DELETE FROM il_sos_llc_agents"))
            db.session.execute(text("DELETE FROM il_sos_llc_entities"))
            db.session.flush()

            imported_at = datetime.utcnow()
            entities: list[IlSosLlcEntity] = []
            entity_keys: set[str] = set()
            for rec in name_recs:
                fn = (rec.get("file_number") or "").strip()
                name = (rec.get("name") or "").strip()
                if not fn or not name:
                    continue
                master = master_recs.get(fn) or {}
                entities.append(IlSosLlcEntity(
                    file_number=fn[:8],
                    name=name[:200],
                    normalized_name=normalize_llc_name(name)[:200],
                    status_code=(master.get("status_code") or None),
                    management_type=(master.get("management_type") or None),
                    juris_organized=(master.get("juris_organized") or None),
                    imported_at=imported_at,
                ))
                entity_keys.add(fn[:8])

            for batch in _chunked(entities, BATCH_SIZE):
                db.session.bulk_save_objects(batch)
                db.session.flush()

            managers: list[IlSosLlcManager] = []
            for rec in manager_recs:
                fn = (rec.get("file_number") or "").strip()[:8]
                if fn not in entity_keys:
                    continue
                mm_name = (rec.get("mm_name") or "").strip()
                if not mm_name:
                    continue
                managers.append(IlSosLlcManager(
                    file_number=fn,
                    mm_name=mm_name[:120],
                    mm_street=_clip(rec.get("mm_street"), 60),
                    mm_city=_clip(rec.get("mm_city"), 40),
                    mm_juris=_clip(rec.get("mm_juris"), 2),
                    mm_zip=format_zip(rec.get("mm_zip")),
                    mm_file_date=_clip(rec.get("mm_file_date"), 20),
                    mm_type_code=_clip(rec.get("mm_type_code"), 1),
                    is_company=is_entity_name(mm_name),
                ))
            for batch in _chunked(managers, BATCH_SIZE):
                db.session.bulk_save_objects(batch)
                db.session.flush()

            agents: list[IlSosLlcAgent] = []
            for fn, rec in agent_recs.items():
                key = fn[:8]
                if key not in entity_keys:
                    continue
                agent_name = (rec.get("agent_name") or "").strip()
                if not agent_name:
                    continue
                agents.append(IlSosLlcAgent(
                    file_number=key,
                    agent_name=agent_name[:120],
                    agent_street=_clip(rec.get("agent_street"), 60),
                    agent_city=_clip(rec.get("agent_city"), 40),
                    agent_zip=format_zip(rec.get("agent_zip")),
                    agent_code=_clip(rec.get("agent_code"), 1),
                ))
            for batch in _chunked(agents, BATCH_SIZE):
                db.session.bulk_save_objects(batch)
                db.session.flush()

            counts["entities_loaded"] = len(entities)
            counts["managers_loaded"] = len(managers)
            counts["agents_loaded"] = len(agents)

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
    ) -> tuple[list[dict], dict[str, dict], list[dict], dict[str, dict], str]:
        cache_dir.mkdir(parents=True, exist_ok=True)

        if prefer_github:
            return self._load_github_csv(cache_dir, force_download=force_download)

        # Prefer already-cached official zips
        official_cached = all(
            (cache_dir / fname).exists() and (cache_dir / fname).stat().st_size > 0
            for fname in FILES.values()
        )
        if official_cached and not force_download:
            return self._load_official_fixed_width(cache_dir, force_download=False)

        try:
            return self._load_official_fixed_width(cache_dir, force_download=force_download)
        except (TimeoutError, URLError, OSError) as exc:
            logger.warning(
                "Official ILSOS download failed (%s); falling back to free GitHub CSV zip",
                exc,
            )
            return self._load_github_csv(cache_dir, force_download=True)

    def _load_official_fixed_width(
        self, cache_dir: Path, *, force_download: bool,
    ) -> tuple[list[dict], dict[str, dict], list[dict], dict[str, dict], str]:
        paths = {
            key: download_ilsos_zip(fname, cache_dir, force=force_download)
            for key, fname in FILES.items()
        }
        name_recs = parse_records(read_zip_text(paths["name"]), NAME_SCHEMA)
        master_recs = {
            r["file_number"]: r
            for r in parse_records(read_zip_text(paths["master"]), MASTER_SCHEMA)
        }
        manager_recs = parse_records(read_zip_text(paths["managers"]), MANAGER_SCHEMA)
        agent_recs = {
            r["file_number"]: r
            for r in parse_records(read_zip_text(paths["agent"]), AGENT_SCHEMA)
        }
        return name_recs, master_recs, manager_recs, agent_recs, "ilsos_transparency_act"

    def _load_github_csv(
        self, cache_dir: Path, *, force_download: bool,
    ) -> tuple[list[dict], dict[str, dict], list[dict], dict[str, dict], str]:
        dest = cache_dir / "llc_github.zip"
        if force_download or not dest.exists() or dest.stat().st_size == 0:
            download_url(GITHUB_LLC_ZIP, dest, timeout=300)
        name_recs = _read_csv_from_zip(dest, "llcallnam.csv")
        master_list = _read_csv_from_zip(dest, "llcallmst.csv")
        master_recs = {r["file_number"]: r for r in master_list if r.get("file_number")}
        manager_recs = _read_csv_from_zip(dest, "llcallmgr.csv")
        agent_list = _read_csv_from_zip(dest, "llcallagt.csv")
        agent_recs = {r["file_number"]: r for r in agent_list if r.get("file_number")}
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
