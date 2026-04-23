"""Enrichment pipeline — merges the four signal sources into a single brief.

The output matches `data/schemas/hiring_signal_brief.schema.json` so the
HubSpot writer, the pitch selector, and the evidence graph can all read a
single artifact per prospect. Every signal carries a confidence so the
outreach composer can shift from assertive to inquisitive language when a
signal is weak.

Signal sources wired in here:
    1. Crunchbase ODM             → firmographics + funding event
    2. Playwright job-post scrape → hiring velocity + AI-adjacent role share
    3. layoffs.fyi CSV            → layoff event
    4. Leadership detection       → CTO / VP-Eng appointment within 90 days

Individual source failures are not fatal — the brief records them in
`data_sources_checked` with status and error so the downstream tone check
can flag a brief that's missing too many sources to be trusted.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from agent.enrichment import ai_maturity, crunchbase, job_posts, layoffs_fyi, leadership

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _signal_inputs_from_results(
    *,
    jobs: job_posts.JobPostResult,
    cb: crunchbase.CrunchbaseResult,
    crunchbase_tech_stack: list[str],
    executive_commentary_source_url: str | None,
    github_org_has_ai_repos: bool | None,
    named_ai_leadership: bool | None,
) -> Iterable[ai_maturity.SignalInput]:
    """Project raw signals into the SignalInput list the maturity scorer expects."""
    inputs: list[ai_maturity.SignalInput] = []

    if jobs.current is not None:
        ai_ratio = (
            jobs.current.ai_adjacent_open_roles / jobs.current.total_open_roles
            if jobs.current.total_open_roles
            else 0.0
        )
        inputs.append(ai_maturity.SignalInput(
            signal="ai_adjacent_open_roles",
            status=(
                f"{jobs.current.ai_adjacent_open_roles} AI-adjacent of "
                f"{jobs.current.total_open_roles} total openings ({ai_ratio:.0%})."
            ),
            weight="high",
            confidence="high" if ai_ratio >= 0.2 else "medium",
        ))

    if named_ai_leadership is not None:
        inputs.append(ai_maturity.SignalInput(
            signal="named_ai_ml_leadership",
            status=(
                "Named Head of AI / VP Data / Chief Scientist on the team page."
                if named_ai_leadership
                else "No public Head of AI, VP Data, or Chief Scientist on the team page."
            ),
            weight="high",
            confidence="high",
        ))

    if github_org_has_ai_repos is not None:
        inputs.append(ai_maturity.SignalInput(
            signal="github_org_activity",
            status=(
                "Recent public commits on AI/ML repos."
                if github_org_has_ai_repos
                else "No public AI repos. Absence is not proof of absence — work may be private."
            ),
            weight="medium",
            confidence="medium",
        ))

    if executive_commentary_source_url:
        inputs.append(ai_maturity.SignalInput(
            signal="executive_commentary",
            status="CEO/CTO post or keynote naming AI as strategic in the last 12 months.",
            weight="medium",
            confidence="medium",
            source_url=executive_commentary_source_url,
        ))

    modern_stack_hits = [
        tech for tech in crunchbase_tech_stack
        if tech.lower() in {"dbt", "snowflake", "databricks", "ray", "vllm", "weights and biases"}
    ]
    if modern_stack_hits:
        inputs.append(ai_maturity.SignalInput(
            signal="modern_data_ml_stack",
            status=f"BuiltWith/Crunchbase stack includes {', '.join(modern_stack_hits)}.",
            weight="low",
            confidence="high",
        ))

    if cb.status == "success" and cb.record and (cb.record.last_funding_stage or "").startswith("series"):
        inputs.append(ai_maturity.SignalInput(
            signal="strategic_communications",
            status="Recent funding press suggests strategic positioning (not direct AI signal).",
            weight="low",
            confidence="low",
        ))

    return inputs


def _segment_classification(
    *,
    funding_stage: str | None,
    funding_date: str | None,
    layoff: layoffs_fyi.LayoffResult,
    leadership_change: leadership.LeadershipResult,
    ai_score: int,
    open_roles: int,
) -> tuple[str, float]:
    """Apply the ICP classification rules from seed/icp_definition.md.

    Returns (segment_enum, confidence). Confidence < 0.6 triggers the
    abstention path in the outreach composer.
    """
    layoff_detected = layoff.event is not None

    if layoff_detected:
        # Rule 1: layoff + funding → Segment 2 (cost pressure dominates).
        conf = 0.8 if open_roles >= 3 else 0.55
        return "segment_2_mid_market_restructure", conf

    if leadership_change.change.detected:
        # Rule 2: new CTO/VP-Eng inside 90 days.
        return "segment_3_leadership_transition", 0.85

    if ai_score >= 2 and open_roles >= 1:
        # Rule 3: specialized capability + maturity gate.
        return "segment_4_specialized_capability", 0.7

    if (funding_stage or "").startswith(("series_a", "series_b")) and funding_date:
        return "segment_1_series_a_b", 0.8 if open_roles >= 5 else 0.55

    return "abstain", 0.4


def run(
    *,
    prospect_name: str,
    prospect_domain: str,
    crunchbase_id: str,
    builtin_url: str | None = None,
    wellfound_url: str | None = None,
    careers_url: str | None = None,
    news_items: list[dict] | None = None,
    executive_commentary_source_url: str | None = None,
    github_org_has_ai_repos: bool | None = None,
    named_ai_leadership: bool | None = None,
    playwright_factory: Any = None,
) -> dict:
    """Run the full enrichment pipeline for a single prospect.

    Returns a dict matching data/schemas/hiring_signal_brief.schema.json.
    """
    cb = crunchbase.lookup(crunchbase_id)
    jobs = job_posts.scrape(
        prospect_domain=prospect_domain,
        builtin_url=builtin_url,
        wellfound_url=wellfound_url,
        careers_url=careers_url,
        playwright_factory=playwright_factory,
    )
    layoff = layoffs_fyi.lookup(prospect_name=prospect_name)
    leadership_result = leadership.detect_from_news(news_items=news_items or [])

    crunchbase_tech_stack: list[str] = []
    if cb.record:
        # Pull tech stack from Crunchbase raw row if populated.
        stack_raw = str(cb.record.raw.get("tech_stack") or cb.record.raw.get("technologies") or "")
        crunchbase_tech_stack = [s.strip() for s in stack_raw.split(",") if s.strip()]

    signals = _signal_inputs_from_results(
        jobs=jobs,
        cb=cb,
        crunchbase_tech_stack=crunchbase_tech_stack,
        executive_commentary_source_url=executive_commentary_source_url,
        github_org_has_ai_repos=github_org_has_ai_repos,
        named_ai_leadership=named_ai_leadership,
    )
    maturity = ai_maturity.score(signals)

    funding_stage = cb.record.last_funding_stage if cb.record else None
    funding_date = cb.record.last_funding_date if cb.record else None
    funding_amount = cb.record.last_funding_amount_usd if cb.record else None
    open_roles = jobs.current.total_open_roles if jobs.current else 0

    segment, segment_conf = _segment_classification(
        funding_stage=funding_stage,
        funding_date=funding_date,
        layoff=layoff,
        leadership_change=leadership_result,
        ai_score=maturity.score,
        open_roles=open_roles,
    )

    honesty_flags = list(_honesty_flags(
        jobs=jobs,
        maturity=maturity,
        layoff=layoff,
        funding_stage=funding_stage,
        crunchbase_tech_stack=crunchbase_tech_stack,
    ))

    data_sources_checked = [
        {"source": "crunchbase_odm", "status": cb.status, "fetched_at": cb.fetched_at,
         **({"error_message": cb.error} if cb.error else {})},
        {"source": "public_job_posts", "status": jobs.status, "fetched_at": jobs.fetched_at,
         **({"error_message": jobs.error} if jobs.error else {})},
        {"source": "layoffs_fyi", "status": layoff.status, "fetched_at": layoff.fetched_at,
         **({"error_message": layoff.error} if layoff.error else {})},
        {"source": "leadership_news", "status": leadership_result.status,
         "fetched_at": leadership_result.fetched_at},
    ]

    return {
        "prospect_domain": prospect_domain,
        "prospect_name": prospect_name,
        "generated_at": _now_iso(),
        "primary_segment_match": segment,
        "segment_confidence": round(segment_conf, 2),
        "ai_maturity": {
            "score": maturity.score,
            "confidence": maturity.confidence_numeric,
            "confidence_label": maturity.confidence_label,
            "phrasing_hint": ai_maturity.phrasing_hint(maturity.score, maturity.confidence_label),
            "justifications": maturity.justifications,
        },
        "hiring_velocity": {
            "open_roles_today": jobs.current.total_open_roles if jobs.current else 0,
            "open_roles_60_days_ago": jobs.prior_60d.total_open_roles if jobs.prior_60d else 0,
            "velocity_label": jobs.velocity_label,
            "signal_confidence": round(jobs.confidence, 2),
            "sources": list(jobs.current.sources) if jobs.current else [],
        },
        "buying_window_signals": {
            "funding_event": {
                "detected": bool(funding_stage),
                "stage": funding_stage or "none",
                "amount_usd": funding_amount,
                "closed_at": funding_date,
                "source_url": f"https://www.crunchbase.com/organization/{crunchbase_id}"
                              if funding_stage else None,
            },
            "layoff_event": (
                {
                    "detected": True,
                    "date": layoff.event.event_date,
                    "headcount_reduction": layoff.event.headcount_reduction,
                    "percentage_cut": layoff.event.percentage_cut,
                    "source_url": layoff.event.source_url,
                }
                if layoff.event
                else {"detected": False}
            ),
            "leadership_change": asdict(leadership_result.change),
        },
        "tech_stack": crunchbase_tech_stack,
        "bench_to_brief_match": {
            # Populated by a separate bench-match step in the composer; the
            # pipeline surfaces stack hints but does not commit capacity.
            "required_stacks": [],
            "bench_available": False,
            "gaps": [],
        },
        "data_sources_checked": data_sources_checked,
        "honesty_flags": honesty_flags,
    }


def _honesty_flags(
    *,
    jobs: job_posts.JobPostResult,
    maturity: ai_maturity.MaturityScore,
    layoff: layoffs_fyi.LayoffResult,
    funding_stage: str | None,
    crunchbase_tech_stack: list[str],
) -> Iterable[str]:
    if jobs.current is None or jobs.current.total_open_roles < 5:
        yield "weak_hiring_velocity_signal"
    if maturity.score >= 2 and maturity.confidence_label == "low":
        yield "weak_ai_maturity_signal"
    if layoff.event and funding_stage and funding_stage.startswith("series"):
        yield "layoff_overrides_funding"
    if crunchbase_tech_stack and not any(
        t.lower() in {"github", "builtwith"} for t in crunchbase_tech_stack
    ):
        yield "tech_stack_inferred_not_confirmed"
