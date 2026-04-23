"""Crunchbase ODM sample lookup.

Reads the luminati-io/Crunchbase-dataset-samples CSV (Apache 2.0, 1,001
companies) from a local path configured via `CRUNCHBASE_ODM_PATH`. If the
file isn't present the module returns a `no_data` record rather than
raising — the pipeline keeps going with the other three sources and flags
the missing coverage in the output brief.
"""
from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrunchbaseRecord:
    crunchbase_id: str
    name: str
    domain: str
    sector: str
    headcount_band: str
    hq_country: str
    last_funding_stage: str | None
    last_funding_amount_usd: int | None
    last_funding_date: str | None
    leadership: list[dict[str, str]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrunchbaseResult:
    status: str  # "success" | "no_data" | "error"
    record: CrunchbaseRecord | None
    confidence: float
    fetched_at: str
    error: str | None = None


def _default_path() -> Path:
    return Path(os.getenv("CRUNCHBASE_ODM_PATH", "data/crunchbase_odm_sample.csv"))


def lookup(crunchbase_id: str, *, path: Path | None = None) -> CrunchbaseResult:
    """Look up a single crunchbase_id in the local ODM sample.

    Confidence is 0.9 for a row we parsed cleanly, 0.0 when the row is missing.
    Firmographic data is a high-confidence source when the record exists — the
    sample is a real Crunchbase export, not inferred data.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    p = path or _default_path()

    if not p.exists():
        log.info("Crunchbase ODM sample not at %s; returning no_data", p)
        return CrunchbaseResult(
            status="no_data",
            record=None,
            confidence=0.0,
            fetched_at=fetched_at,
            error=f"ODM file not found at {p}",
        )

    try:
        with p.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if str(row.get("uuid") or row.get("crunchbase_id") or "").strip() != crunchbase_id:
                    continue
                return CrunchbaseResult(
                    status="success",
                    record=_row_to_record(row, crunchbase_id),
                    confidence=0.9,
                    fetched_at=fetched_at,
                )
    except (OSError, csv.Error) as exc:
        log.exception("Crunchbase ODM read failed")
        return CrunchbaseResult(
            status="error",
            record=None,
            confidence=0.0,
            fetched_at=fetched_at,
            error=str(exc),
        )

    return CrunchbaseResult(
        status="no_data",
        record=None,
        confidence=0.0,
        fetched_at=fetched_at,
        error=f"crunchbase_id {crunchbase_id} not in sample",
    )


def _row_to_record(row: dict[str, str], crunchbase_id: str) -> CrunchbaseRecord:
    amount_raw = row.get("last_funding_total") or row.get("last_funding_amount") or ""
    amount: int | None
    try:
        amount = int(float(amount_raw)) if amount_raw else None
    except ValueError:
        amount = None
    return CrunchbaseRecord(
        crunchbase_id=crunchbase_id,
        name=row.get("name") or row.get("company_name") or "",
        domain=row.get("domain") or row.get("homepage_url") or "",
        sector=row.get("categories") or row.get("category_list") or "",
        headcount_band=row.get("employee_count") or row.get("num_employees_enum") or "",
        hq_country=row.get("country_code") or row.get("country") or "",
        last_funding_stage=row.get("last_funding_type") or None,
        last_funding_amount_usd=amount,
        last_funding_date=row.get("last_funding_at") or None,
        leadership=_parse_leadership(row),
        raw=dict(row),
    )


def _parse_leadership(row: dict[str, str]) -> list[dict[str, str]]:
    """Best-effort extraction of leadership names from common ODM columns."""
    names = (row.get("founders") or row.get("people") or "").split(";")
    return [{"name": n.strip()} for n in names if n.strip()]
