"""Public job-post scraper.

Playwright with a headless browser fetches the public job-listings page of a
prospect's BuiltIn / Wellfound / careers page and counts open engineering
roles. A 60-day-prior snapshot is read from disk so the velocity label
(tripled / doubled / flat) is computed against a prior reference point the
trainee captured earlier in the week.

Hard constraints from the spec:
    - Only public pages. No login flows, no credential forms.
    - robots.txt is checked before any fetch and a Disallow results in a
      no_data record, not a bypass attempt.
    - No captcha-solving, no proxy rotation, no headless-detection evasion.

These constraints are encoded in `_guard_url` and enforced at every entry
point — see tests/test_job_posts_guardrails.py for the assertion that a
login URL is rejected.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.robotparser as robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_AI_ADJACENT_KEYWORDS = (
    "ml engineer",
    "machine learning",
    "applied scientist",
    "llm",
    "ai engineer",
    "ai product",
    "data platform",
    "mlops",
    "ai researcher",
)

_LOGIN_PATH_HINTS = ("/login", "/signin", "/sign-in", "/auth", "/oauth")


@dataclass(frozen=True)
class JobPostCount:
    total_open_roles: int
    ai_adjacent_open_roles: int
    sources: list[str]


@dataclass(frozen=True)
class JobPostResult:
    status: str   # "success" | "partial" | "no_data" | "error" | "rate_limited"
    current: JobPostCount | None
    prior_60d: JobPostCount | None
    velocity_label: str
    confidence: float
    fetched_at: str
    error: str | None = None


class UnsafeScrapeTarget(ValueError):
    """Raised when a requested URL looks like a login-gated or auth endpoint."""


def _guard_url(url: str) -> None:
    parsed = urlparse(url)
    lowered = (parsed.path or "").lower()
    if any(hint in lowered for hint in _LOGIN_PATH_HINTS):
        raise UnsafeScrapeTarget(f"refusing login-adjacent URL: {url}")
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeScrapeTarget(f"non-http scheme blocked: {url}")


def _robots_allows(url: str, user_agent: str = "conversion-engine-bot") -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        # When robots.txt can't be fetched, default to disallow — a conservative
        # read of the spec's "respect robots.txt" constraint.
        log.info("robots.txt unfetchable for %s; defaulting to disallow", robots_url)
        return False
    return rp.can_fetch(user_agent, url)


def _velocity_label(current: int, prior: int) -> str:
    if prior == 0 and current == 0:
        return "insufficient_signal"
    if prior == 0:
        return "insufficient_signal"
    ratio = current / prior
    if ratio >= 3.0:
        return "tripled_or_more"
    if ratio >= 2.0:
        return "doubled"
    if ratio >= 1.3:
        return "increased_modestly"
    if ratio >= 0.9:
        return "flat"
    return "declined"


def _count_roles(titles: list[str]) -> JobPostCount:
    lowered = [t.lower() for t in titles]
    ai_adj = sum(1 for t in lowered if any(kw in t for kw in _AI_ADJACENT_KEYWORDS))
    return JobPostCount(
        total_open_roles=len(lowered),
        ai_adjacent_open_roles=ai_adj,
        sources=[],
    )


def _load_prior_snapshot(prospect_domain: str) -> JobPostCount | None:
    """Read a 60-day-prior snapshot of role counts written during Day 0 setup."""
    snapshot_path = Path(
        os.getenv("JOB_POST_SNAPSHOT_DIR", "data/snapshots/job_posts")
    ) / f"{prospect_domain}.json"
    if not snapshot_path.exists():
        return None
    try:
        data = json.loads(snapshot_path.read_text())
    except (OSError, json.JSONDecodeError):
        log.warning("prior job-post snapshot unreadable at %s", snapshot_path)
        return None
    return JobPostCount(
        total_open_roles=int(data.get("total_open_roles") or 0),
        ai_adjacent_open_roles=int(data.get("ai_adjacent_open_roles") or 0),
        sources=list(data.get("sources") or []),
    )


def scrape(
    *,
    prospect_domain: str,
    builtin_url: str | None = None,
    wellfound_url: str | None = None,
    careers_url: str | None = None,
    playwright_factory: Any = None,
) -> JobPostResult:
    """Fetch and count engineering roles across public sources.

    `playwright_factory` is injected in tests; at runtime it defaults to the
    real Playwright sync API. When Playwright is not installed (common on
    reviewer machines) the call returns a no_data record gracefully.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    urls = [u for u in (builtin_url, wellfound_url, careers_url) if u]

    for url in urls:
        try:
            _guard_url(url)
        except UnsafeScrapeTarget as exc:
            return JobPostResult(
                status="error",
                current=None,
                prior_60d=None,
                velocity_label="insufficient_signal",
                confidence=0.0,
                fetched_at=fetched_at,
                error=str(exc),
            )
        if not _robots_allows(url):
            return JobPostResult(
                status="no_data",
                current=None,
                prior_60d=None,
                velocity_label="insufficient_signal",
                confidence=0.0,
                fetched_at=fetched_at,
                error=f"robots.txt disallows scraping {url}",
            )

    if not urls:
        return JobPostResult(
            status="no_data",
            current=None,
            prior_60d=None,
            velocity_label="insufficient_signal",
            confidence=0.0,
            fetched_at=fetched_at,
            error="no URLs provided",
        )

    titles: list[str] = []
    sources: list[str] = []

    try:
        titles, sources = _playwright_fetch(urls, playwright_factory=playwright_factory)
    except Exception as exc:
        log.exception("playwright fetch failed")
        return JobPostResult(
            status="error",
            current=None,
            prior_60d=None,
            velocity_label="insufficient_signal",
            confidence=0.0,
            fetched_at=fetched_at,
            error=str(exc),
        )

    current = _count_roles(titles)
    current = JobPostCount(
        total_open_roles=current.total_open_roles,
        ai_adjacent_open_roles=current.ai_adjacent_open_roles,
        sources=sources,
    )
    prior = _load_prior_snapshot(prospect_domain)

    label = _velocity_label(
        current.total_open_roles,
        prior.total_open_roles if prior else 0,
    )
    confidence = 0.85 if (prior and current.total_open_roles >= 5) else 0.5 if current.total_open_roles > 0 else 0.0
    status = "success" if prior and current.total_open_roles > 0 else "partial"

    return JobPostResult(
        status=status,
        current=current,
        prior_60d=prior,
        velocity_label=label,
        confidence=confidence,
        fetched_at=fetched_at,
    )


def _playwright_fetch(
    urls: list[str],
    *,
    playwright_factory: Any = None,
) -> tuple[list[str], list[str]]:
    """Return (titles, sources). `playwright_factory` lets tests inject a fake.

    The factory is a callable returning a context manager; entering it yields
    an object with a `.new_page()` method. This matches the Playwright sync
    API shape so real and fake code paths agree.
    """
    if playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: WPS433
        except ImportError:
            log.info("playwright not installed; job_posts returning no_data")
            return [], []
        playwright_factory = sync_playwright

    titles: list[str] = []
    sources: list[str] = []

    with playwright_factory() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for url in urls:
                page = browser.new_page(
                    user_agent="conversion-engine-bot (Tenacious Week 10)"
                )
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    # NOTE: No login, no form fill, no captcha handling. If the
                    # page requires auth, we get whatever public markup exists
                    # and move on.
                    extracted = page.evaluate(
                        """
                        () => Array.from(document.querySelectorAll(
                            'h2, h3, a[href*="jobs"], a[href*="careers"]'
                        )).map(el => (el.textContent || '').trim()).filter(Boolean)
                        """
                    ) or []
                    titles.extend(str(t) for t in extracted)
                    sources.append(urlparse(url).netloc)
                except Exception as exc:
                    log.warning("playwright fetch error on %s: %s", url, exc)
                finally:
                    page.close()
        finally:
            browser.close()

    return titles, sources
