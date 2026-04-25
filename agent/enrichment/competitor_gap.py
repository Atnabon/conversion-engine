"""Competitor gap brief builder.

Given a prospect's sector and AI-maturity score, this module:
    1. Discovers 5-10 top-quartile peer companies in the same sector + size cell
       (`discover_top_quartile_peers`).
    2. Re-uses the AI-maturity scoring rubric on each peer
       (`score_peer_ai_maturity`).
    3. Computes the prospect's distribution position relative to peers
       (`compute_distribution_position`).
    4. Extracts 1-3 gap findings, each with public-signal evidence + a
       confidence label.
    5. Assembles the final brief matching `data/schemas/competitor_gap_brief.schema.json`.

Sparse-sector handling: when fewer than 5 viable peers are available,
`build` returns a degraded brief with `gap_findings = []` and a flag in
`gap_quality_self_check.sparse_sector` so the composer suppresses gap
language and falls back to the hiring-signal brief alone — rather than
raising and breaking the pipeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from agent.enrichment import ai_maturity

log = logging.getLogger(__name__)

MIN_PEERS = 5
MAX_PEERS = 10


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


@dataclass(frozen=True)
class DistributionPosition:
    """Where the prospect sits in the sector AI-maturity distribution."""
    percentile: float           # 0.0–1.0
    above_top_quartile: bool
    below_top_quartile: bool
    n_peers_compared: int
    top_quartile_threshold: float


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


# ---------------------------------------------------------------------------
# Peer discovery
# ---------------------------------------------------------------------------

def discover_top_quartile_peers(
    *,
    prospect_domain: str,
    prospect_sector: str,
    prospect_headcount_band: str,
    candidate_pool: Iterable[dict],
    score_signals_for: Callable[[dict], Iterable[ai_maturity.SignalInput]],
    max_peers: int = MAX_PEERS,
) -> list[PeerCompany]:
    """Pick 5-10 sector + size-band peers from a candidate pool.

    Selection criteria (documented per the rubric):
      1. EXCLUDE the prospect itself (matched by `domain`).
      2. INCLUDE only candidates whose `categories` overlaps `prospect_sector`.
      3. INCLUDE only candidates whose `headcount_band` matches the prospect's.
      4. SCORE every candidate via the same AI-maturity rubric used on the
         prospect (`score_signals_for` returns the SignalInput list).
      5. RANK by maturity score (descending), with a stable secondary sort
         by domain so two runs against the same pool produce the same brief.
      6. Take the top N peers up to MAX_PEERS (10) and return them.

    The caller is responsible for sourcing the candidate pool — typically
    by filtering the Crunchbase ODM CSV for `categories LIKE %sector%` AND
    `employee_count == prospect_headcount_band`. `score_signals_for` is
    injected so this module stays decoupled from any specific signal source.
    """
    needle_sector = (prospect_sector or "").lower().strip()

    candidates: list[PeerCompany] = []
    for row in candidate_pool:
        domain = str(row.get("domain") or "").strip().lower()
        if not domain or domain == prospect_domain.lower().strip():
            continue
        categories = str(row.get("categories") or row.get("sector") or "").lower()
        if needle_sector and needle_sector not in categories:
            continue
        if str(row.get("headcount_band") or row.get("employee_count") or "") != prospect_headcount_band:
            continue
        signals = list(score_signals_for(row))
        if not signals:
            continue
        peer = score_peer_ai_maturity(
            name=str(row.get("name") or row.get("company_name") or domain),
            domain=domain,
            signals=signals,
            headcount_band=str(
                row.get("headcount_band") or row.get("employee_count") or ""
            ),
            sources_checked=list(row.get("sources_checked") or []),
        )
        candidates.append(peer)

    candidates.sort(key=lambda p: (-p.ai_maturity_score, p.domain))
    return candidates[:max_peers]


# ---------------------------------------------------------------------------
# Distribution position
# ---------------------------------------------------------------------------

def compute_distribution_position(
    *,
    prospect_score: int,
    peers: list[PeerCompany],
) -> DistributionPosition:
    """Compute where the prospect sits relative to the peer distribution.

    Percentile is the fraction of peers strictly below the prospect's score,
    so percentile = 0.0 means rock-bottom in the cell and 1.0 means top.
    """
    if not peers:
        return DistributionPosition(
            percentile=0.0,
            above_top_quartile=False,
            below_top_quartile=False,
            n_peers_compared=0,
            top_quartile_threshold=0.0,
        )
    threshold = _top_quartile_threshold(peers)
    n_below = sum(1 for p in peers if p.ai_maturity_score < prospect_score)
    percentile = n_below / len(peers)
    return DistributionPosition(
        percentile=round(percentile, 3),
        above_top_quartile=prospect_score >= threshold,
        below_top_quartile=prospect_score < threshold,
        n_peers_compared=len(peers),
        top_quartile_threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Brief assembly
# ---------------------------------------------------------------------------

def build(
    *,
    prospect_domain: str,
    prospect_sector: str,
    prospect_sub_niche: str | None,
    prospect_ai_maturity: int,
    peers: list[PeerCompany],
    practices: list[PracticeCandidate],
) -> dict:
    """Compose a competitor_gap_brief matching the JSON schema.

    Sparse-sector behaviour: when `len(peers) < MIN_PEERS`, returns a brief
    with `gap_findings = []`, a `sparse_sector` flag, and a degraded
    `suggested_pitch_shift` that tells the composer to fall back to the
    hiring-signal brief alone. Does not raise.
    """
    sparse = len(peers) < MIN_PEERS

    # Cap upper bound but tolerate sparsity at the lower bound.
    peers = peers[:MAX_PEERS]
    if not sparse and not (1 <= len(practices) <= 3):
        raise ValueError(
            f"competitor_gap brief requires 1-3 gap findings; got {len(practices)}"
        )

    threshold = _top_quartile_threshold(peers)
    top_quartile = [p for p in peers if _is_top_quartile(p, threshold)]
    top_q_mean = (
        sum(p.ai_maturity_score for p in top_quartile) / len(top_quartile)
        if top_quartile else 0.0
    )

    competitors_payload = [
        {
            "name": p.name,
            "domain": p.domain,
            "ai_maturity_score": p.ai_maturity_score,
            "ai_maturity_justification": p.ai_maturity_justification,
            "headcount_band": p.headcount_band,
            "top_quartile": _is_top_quartile(p, threshold),
            "sources_checked": p.sources_checked,
        }
        for p in peers
    ]

    if sparse:
        gap_findings: list[dict] = []
        log.info(
            "competitor_gap: sparse sector for %s (n_peers=%d); "
            "returning degraded brief with no gap findings",
            prospect_domain, len(peers),
        )
    else:
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

    all_have_source = (
        bool(gap_findings) and all(
            all(ev.get("source_url") for ev in pc.peer_evidence)
            for pc in practices
        )
    )
    any_high_conf = any(pc.confidence == "high" for pc in practices)

    distribution = compute_distribution_position(
        prospect_score=prospect_ai_maturity, peers=peers,
    )

    return {
        "prospect_domain": prospect_domain,
        "prospect_sector": prospect_sector,
        "prospect_sub_niche": prospect_sub_niche,
        "generated_at": _now_iso(),
        "prospect_ai_maturity_score": prospect_ai_maturity,
        "sector_top_quartile_benchmark": round(top_q_mean, 2),
        "prospect_distribution_position": {
            "percentile": distribution.percentile,
            "above_top_quartile": distribution.above_top_quartile,
            "below_top_quartile": distribution.below_top_quartile,
            "n_peers_compared": distribution.n_peers_compared,
            "top_quartile_threshold": distribution.top_quartile_threshold,
        },
        "competitors_analyzed": competitors_payload,
        "gap_findings": gap_findings,
        "suggested_pitch_shift": (
            _sparse_pitch_shift()
            if sparse
            else _suggest_pitch_shift(prospect_ai_maturity, top_q_mean)
        ),
        "gap_quality_self_check": {
            "all_peer_evidence_has_source_url": all_have_source,
            "at_least_one_gap_high_confidence": any_high_conf,
            "prospect_silent_but_sophisticated_risk": False,
            "sparse_sector": sparse,
            "n_peers_required_min": MIN_PEERS,
            "n_peers_found": len(peers),
        },
    }


def _sparse_pitch_shift() -> str:
    return (
        "Sparse sector — fewer than 5 comparable peers found. "
        "Suppress competitor-gap language and lead with the hiring-signal "
        "brief alone (funding event, hiring velocity, layoffs, leadership "
        "change). Do not assert sector trends from too few peers."
    )


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
    """Convenience wrapper that reuses the maturity scorer on a peer company.

    Crucially, this is the *same* `ai_maturity.score()` function used to
    score the prospect — peer and prospect scores are directly comparable
    by construction.
    """
    score = ai_maturity.score(signals)
    return PeerCompany(
        name=name,
        domain=domain,
        ai_maturity_score=score.score,
        ai_maturity_justification=[j["status"] for j in score.justifications],
        headcount_band=headcount_band,
        sources_checked=list(sources_checked or []),
    )
