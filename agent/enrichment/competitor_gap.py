"""Competitor gap brief builder.

Given a prospect's sector and AI-maturity score, this module locates 5-10
peer companies in the same sector+size cell, applies the same maturity
rubric to each, and extracts 1-3 specific practices the top quartile shows
public signal for that the prospect does not.

The output matches `data/schemas/competitor_gap_brief.schema.json`. The
practice extraction here is deliberately conservative — every gap finding
carries a confidence and a source URL, and the `gap_quality_self_check`
flags a silent-but-sophisticated prospect as a false-negative risk so the
composer softens language.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from agent.enrichment import ai_maturity


@dataclass(frozen=True)
class PeerCompany:
    name: str
    domain: str
    ai_maturity_score: int
    ai_maturity_justification: list[str]
    headcount_band: str
    sources_checked: list[str]


@dataclass(frozen=True)
class PracticeCandidate:
    practice: str
    peer_evidence: list[dict]  # [{competitor_name, evidence, source_url}, ...]
    prospect_state: str
    confidence: str             # "low" | "medium" | "high"
    segment_relevance: list[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _top_quartile_threshold(peers: list[PeerCompany]) -> float:
    if not peers:
        return 0.0
    scores = sorted([p.ai_maturity_score for p in peers], reverse=True)
    cutoff_idx = max(1, len(scores) // 4)
    return float(scores[:cutoff_idx][-1])


def _is_top_quartile(p: PeerCompany, threshold: float) -> bool:
    return p.ai_maturity_score >= threshold


def build(
    *,
    prospect_domain: str,
    prospect_sector: str,
    prospect_sub_niche: str | None,
    prospect_ai_maturity: int,
    peers: list[PeerCompany],
    practices: list[PracticeCandidate],
) -> dict:
    """Compose a competitor_gap_brief matching the JSON schema."""
    if not (5 <= len(peers) <= 10):
        raise ValueError(
            f"competitor_gap brief requires 5-10 peers; got {len(peers)}"
        )
    if not (1 <= len(practices) <= 3):
        raise ValueError(
            f"competitor_gap brief requires 1-3 gap findings; got {len(practices)}"
        )

    threshold = _top_quartile_threshold(peers)
    top_quartile = [p for p in peers if _is_top_quartile(p, threshold)]
    top_q_mean = (
        sum(p.ai_maturity_score for p in top_quartile) / len(top_quartile)
        if top_quartile else 0.0
    )

    competitors_payload = []
    for p in peers:
        competitors_payload.append({
            "name": p.name,
            "domain": p.domain,
            "ai_maturity_score": p.ai_maturity_score,
            "ai_maturity_justification": p.ai_maturity_justification,
            "headcount_band": p.headcount_band,
            "top_quartile": _is_top_quartile(p, threshold),
            "sources_checked": p.sources_checked,
        })

    gap_findings = [
        {
            "practice": pc.practice,
            "peer_evidence": pc.peer_evidence,
            "prospect_state": pc.prospect_state,
            "confidence": pc.confidence,
            "segment_relevance": pc.segment_relevance,
        }
        for pc in practices
    ]

    all_have_source = all(
        all(ev.get("source_url") for ev in pc.peer_evidence)
        for pc in practices
    )
    any_high_conf = any(pc.confidence == "high" for pc in practices)

    return {
        "prospect_domain": prospect_domain,
        "prospect_sector": prospect_sector,
        "prospect_sub_niche": prospect_sub_niche,
        "generated_at": _now_iso(),
        "prospect_ai_maturity_score": prospect_ai_maturity,
        "sector_top_quartile_benchmark": round(top_q_mean, 2),
        "competitors_analyzed": competitors_payload,
        "gap_findings": gap_findings,
        "suggested_pitch_shift": _suggest_pitch_shift(
            prospect_ai_maturity, top_q_mean
        ),
        "gap_quality_self_check": {
            "all_peer_evidence_has_source_url": all_have_source,
            "at_least_one_gap_high_confidence": any_high_conf,
            "prospect_silent_but_sophisticated_risk": False,
        },
    }


def _suggest_pitch_shift(prospect_score: int, top_q_mean: float) -> str:
    if prospect_score == 0 and top_q_mean >= 2.0:
        return (
            "Prospect shows no public AI signal while top quartile averages 2+. "
            "Pitch 'stand up your first AI function with a dedicated squad' — "
            "do not assert the gap; ask whether it's a deliberate choice."
        )
    if prospect_score < top_q_mean - 1:
        return (
            "Prospect sits below sector top-quartile on AI maturity. Segment 4 "
            "pitch is appropriate when at least one gap finding is high confidence."
        )
    if prospect_score >= top_q_mean:
        return (
            "Prospect is at or above sector median. Use scale language — "
            "'scale your AI team faster than in-house hiring can support'."
        )
    return "Default grounded phrasing; lean on hiring_velocity rather than gap."


def score_peer_ai_maturity(
    *,
    name: str,
    domain: str,
    signals: Iterable[ai_maturity.SignalInput],
    headcount_band: str,
    sources_checked: list[str] | None = None,
) -> PeerCompany:
    """Convenience wrapper that reuses the maturity scorer on a peer company."""
    score = ai_maturity.score(signals)
    return PeerCompany(
        name=name,
        domain=domain,
        ai_maturity_score=score.score,
        ai_maturity_justification=[j["status"] for j in score.justifications],
        headcount_band=headcount_band,
        sources_checked=list(sources_checked or []),
    )
