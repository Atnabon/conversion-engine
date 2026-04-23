"""Leadership-change detection.

Two inputs:
    - Crunchbase record leadership roster (if available)
    - Public press / Crunchbase news page checked for CTO/VP-Engineering
      appointment language within a 90-day window

A detected change inside the 90-day window triggers Segment 3 (engineering-
leadership transition) in the ICP classifier and shifts the outreach opening
line. The detection is deliberately conservative — a weak match returns
`detected=False` rather than a low-confidence true.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

log = logging.getLogger(__name__)


_ROLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "cto": re.compile(r"\bchief\s+technology\s+officer\b|\bcto\b", re.IGNORECASE),
    "vp_engineering": re.compile(r"\bvp\s+(of\s+)?engineering\b", re.IGNORECASE),
    "cio": re.compile(r"\bchief\s+information\s+officer\b|\bcio\b", re.IGNORECASE),
    "chief_data_officer": re.compile(r"\bchief\s+data\s+officer\b|\bcdo\b", re.IGNORECASE),
    "head_of_ai": re.compile(r"\bhead\s+of\s+ai\b", re.IGNORECASE),
}

_APPOINTED_VERB = re.compile(
    r"\b(appointed|named|joins|joined|hired|promoted\s+to|new)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LeadershipChange:
    detected: bool
    role: str           # one of _ROLE_PATTERNS keys, or "none"
    new_leader_name: str | None
    started_at: str | None  # ISO date, None when inferred
    source_url: str | None
    evidence_excerpt: str | None


@dataclass(frozen=True)
class LeadershipResult:
    status: str  # "success" | "no_data" | "error"
    change: LeadershipChange
    confidence: float
    fetched_at: str


def _within_window(d: date, today: date, window_days: int) -> bool:
    return (today - d).days <= window_days


def detect_from_news(
    *,
    news_items: Iterable[dict],
    today: date | None = None,
    window_days: int = 90,
) -> LeadershipResult:
    """Scan a list of news/press items for a matching appointment.

    `news_items` is a list of dicts with at least `title`, `published_at`
    (ISO date string), and optionally `url` and `body`. A caller can supply
    Crunchbase news results, a company /press feed, or a curated snapshot.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    now = today or datetime.now(timezone.utc).date()

    try:
        best: tuple[date, LeadershipChange] | None = None
        for item in news_items:
            title = str(item.get("title") or "")
            body = str(item.get("body") or "")
            text = f"{title}\n{body}"
            if not _APPOINTED_VERB.search(text):
                continue
            role_match = _first_role_match(text)
            if role_match is None:
                continue
            date_raw = item.get("published_at")
            event_date = _parse_iso_date(date_raw)
            if event_date is None or not _within_window(event_date, now, window_days):
                continue
            change = LeadershipChange(
                detected=True,
                role=role_match,
                new_leader_name=_extract_person_name(text),
                started_at=event_date.isoformat(),
                source_url=item.get("url"),
                evidence_excerpt=title or body[:200],
            )
            if best is None or event_date > best[0]:
                best = (event_date, change)

        if best is None:
            return LeadershipResult(
                status="success",
                change=LeadershipChange(
                    detected=False,
                    role="none",
                    new_leader_name=None,
                    started_at=None,
                    source_url=None,
                    evidence_excerpt=None,
                ),
                confidence=0.85,
                fetched_at=fetched_at,
            )

        return LeadershipResult(
            status="success",
            change=best[1],
            confidence=0.8,
            fetched_at=fetched_at,
        )
    except Exception:
        log.exception("leadership detection failed")
        return LeadershipResult(
            status="error",
            change=LeadershipChange(
                detected=False,
                role="none",
                new_leader_name=None,
                started_at=None,
                source_url=None,
                evidence_excerpt=None,
            ),
            confidence=0.0,
            fetched_at=fetched_at,
        )


def _first_role_match(text: str) -> str | None:
    for role_name, pattern in _ROLE_PATTERNS.items():
        if pattern.search(text):
            return role_name
    return None


_PERSON_NAME_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+(?:joins|joined|has\s+joined|as\s+|named|appointed)",
)


def _extract_person_name(text: str) -> str | None:
    match = _PERSON_NAME_RE.search(text)
    if match:
        return match.group(1)
    return None


def _parse_iso_date(raw) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None
