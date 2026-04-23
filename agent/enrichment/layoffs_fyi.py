"""layoffs.fyi signal extraction.

Reads the structured CC-BY CSV (downloaded to `data/layoffs_fyi.csv` at
Day-0 setup) and surfaces any event matching the prospect within a 120-day
window. The dataset schema drifts occasionally, so the parser tolerates a
few common column-name variants rather than failing on a rename.
"""
from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayoffEvent:
    company: str
    event_date: str
    headcount_reduction: int | None
    percentage_cut: float | None
    source_url: str | None


@dataclass(frozen=True)
class LayoffResult:
    status: str  # "success" | "no_data" | "error"
    event: LayoffEvent | None
    confidence: float
    fetched_at: str
    error: str | None = None


_COMPANY_COLS = ("company", "Company", "company_name")
_DATE_COLS = ("date", "Date", "event_date", "layoff_date")
_HEADCOUNT_COLS = ("laid_off", "total_laid_off", "# Laid Off", "headcount")
_PCT_COLS = ("percentage", "percent_laid_off", "# Percentage")
_SOURCE_COLS = ("source", "Source", "source_url")


def _read_col(row: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        if key in row and (row[key] or "").strip():
            return row[key].strip()
    return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _default_path() -> Path:
    return Path(os.getenv("LAYOFFS_FYI_CSV_PATH", "data/layoffs_fyi.csv"))


def lookup(
    *,
    prospect_name: str,
    window_days: int = 120,
    today: date | None = None,
    path: Path | None = None,
) -> LayoffResult:
    fetched_at = datetime.now(timezone.utc).isoformat()
    p = path or _default_path()
    if not p.exists():
        return LayoffResult(
            status="no_data",
            event=None,
            confidence=0.0,
            fetched_at=fetched_at,
            error=f"layoffs.fyi CSV not found at {p}",
        )

    now = today or datetime.now(timezone.utc).date()
    cutoff = now - timedelta(days=window_days)
    needle = prospect_name.strip().lower()

    try:
        with p.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            best: tuple[date, LayoffEvent] | None = None
            for row in reader:
                company = _read_col(row, _COMPANY_COLS)
                if not company or company.strip().lower() != needle:
                    continue
                event_date = _parse_date(_read_col(row, _DATE_COLS))
                if event_date is None or event_date < cutoff:
                    continue
                headcount = _read_col(row, _HEADCOUNT_COLS)
                pct = _read_col(row, _PCT_COLS)
                try:
                    hc_int = int(float(headcount)) if headcount else None
                except ValueError:
                    hc_int = None
                try:
                    pct_f = float(pct) if pct else None
                except ValueError:
                    pct_f = None
                event = LayoffEvent(
                    company=company,
                    event_date=event_date.isoformat(),
                    headcount_reduction=hc_int,
                    percentage_cut=pct_f,
                    source_url=_read_col(row, _SOURCE_COLS),
                )
                if best is None or event_date > best[0]:
                    best = (event_date, event)
    except (OSError, csv.Error) as exc:
        log.exception("layoffs.fyi CSV read failed")
        return LayoffResult(
            status="error",
            event=None,
            confidence=0.0,
            fetched_at=fetched_at,
            error=str(exc),
        )

    if best is None:
        return LayoffResult(
            status="success",
            event=None,
            confidence=0.9,
            fetched_at=fetched_at,
        )

    return LayoffResult(
        status="success",
        event=best[1],
        confidence=0.9,
        fetched_at=fetched_at,
    )
