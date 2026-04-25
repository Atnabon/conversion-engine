"""AI-maturity scoring (0-3) with per-signal justification and confidence.

High-weight inputs: AI-adjacent open roles, named AI/ML leadership.
Medium-weight inputs: GitHub org activity, executive commentary.
Low-weight inputs: modern data/ML stack, strategic communications.

Combination rule (per seed/icp_definition.md):
    - Each high-weight signal that fires contributes 1.0 to the raw score
      when backed by high-confidence evidence, 0.5 when medium, 0.25 when low.
    - Medium-weight signals contribute at half those magnitudes.
    - Low-weight signals contribute at one quarter.
    - The raw sum is clamped to [0, 3.75] then floored to an integer 0-3.

Confidence in the final score is derived from the evidence weights, not
from the score magnitude:
    - high: >=2 high-weight inputs with high-confidence evidence
    - medium: any high-weight input with >=medium evidence, or >=3 signals
    - low: everything else (and scores from inferred signals only)

Low confidence paired with a high score is the critical flag — it triggers
the "ask rather than assert" phrasing in the outreach composer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

_WEIGHT_TO_BASE = {"high": 1.0, "medium": 0.5, "low": 0.25}
_CONFIDENCE_SCALE = {"high": 1.0, "medium": 0.5, "low": 0.25}
_SCORE_MAX = 3


@dataclass(frozen=True)
class SignalInput:
    signal: str          # one of the six enum values from the schema
    status: str          # free-text description of what was found
    weight: str          # "high" | "medium" | "low"
    confidence: str      # "high" | "medium" | "low"
    source_url: str | None = None


SILENT_COMPANY_DISCLAIMER = (
    "No public AI signal found. Absence is not proof of absence — many "
    "companies keep AI work private (private repos, internal tooling, "
    "no public exec commentary). The agent must phrase any AI reference "
    "to a score-0 prospect as a question, not an assertion, and may not "
    "use Segment 4 (specialized capability gap) language."
)


@dataclass(frozen=True)
class MaturityScore:
    score: int
    confidence_label: str            # "low" | "medium" | "high"
    confidence_numeric: float        # 0.0-1.0 — for schema field
    justifications: list[dict]
    raw_points: float
    silent_company: bool              # True when no public signal at all
    silent_company_disclaimer: str | None


def score(signals: Iterable[SignalInput]) -> MaturityScore:
    """Compute the 0-3 maturity score from a list of SignalInputs.

    Silent-company handling (rubric requirement): if the input list is
    empty OR every signal contributes zero points (weight=0 or confidence=0),
    return `score = 0` with `silent_company = True` and a disclaimer string
    that the composer must surface alongside any AI-maturity reference.
    Score 0 is also reachable from non-silent inputs (low-confidence,
    low-weight signals that round down) — `silent_company` distinguishes
    the two cases so the composer phrasing differs.
    """
    signals_list = list(signals)
    raw = 0.0
    justifications: list[dict] = []

    high_weight_firing = 0
    total_weighted_evidence = 0.0

    for s in signals_list:
        base = _WEIGHT_TO_BASE.get(s.weight, 0.0)
        scale = _CONFIDENCE_SCALE.get(s.confidence, 0.0)
        points = base * scale
        raw += points
        total_weighted_evidence += points
        if s.weight == "high" and points > 0:
            high_weight_firing += 1
        entry = {
            "signal": s.signal,
            "status": s.status,
            "weight": s.weight,
            "confidence": s.confidence,
        }
        if s.source_url:
            entry["source_url"] = s.source_url
        justifications.append(entry)

    raw = min(raw, float(_SCORE_MAX) + 0.75)
    integer_score = min(int(raw), _SCORE_MAX)

    silent_company = (not signals_list) or total_weighted_evidence == 0.0
    if silent_company and not justifications:
        # Surface the disclaimer in the justifications list so the schema
        # consumer always sees something for a silent company.
        justifications.append({
            "signal": "no_public_signal",
            "status": SILENT_COMPANY_DISCLAIMER,
            "weight": "low",
            "confidence": "high",
        })

    confidence_label = _confidence_label(
        high_weight_firing,
        signals_count=len(signals_list),
        evidence_mass=total_weighted_evidence,
    )
    confidence_numeric = _confidence_numeric(confidence_label)

    return MaturityScore(
        score=integer_score,
        confidence_label=confidence_label,
        confidence_numeric=confidence_numeric,
        justifications=justifications,
        raw_points=raw,
        silent_company=silent_company,
        silent_company_disclaimer=SILENT_COMPANY_DISCLAIMER if silent_company else None,
    )


def _confidence_label(
    high_weight_firing: int,
    *,
    signals_count: int,
    evidence_mass: float,
) -> str:
    if high_weight_firing >= 2 and evidence_mass >= 2.0:
        return "high"
    if high_weight_firing >= 1 and evidence_mass >= 1.0:
        return "medium"
    if signals_count >= 3 and evidence_mass >= 1.0:
        return "medium"
    return "low"


def _confidence_numeric(label: str) -> float:
    return {"high": 0.85, "medium": 0.6, "low": 0.3}[label]


def phrasing_hint(score_value: int, confidence_label: str) -> str:
    """Return the phrasing directive the outreach composer should respect.

    This is the contract the tone-preservation probe tests against — a
    low-confidence high score must trigger ask-rather-than-assert language
    as documented in seed/style_guide.md.
    """
    if score_value >= 2 and confidence_label == "low":
        return "ask_rather_than_assert"
    if score_value <= 1:
        return "lead_with_stand_up_language"
    if score_value >= 2 and confidence_label == "high":
        return "lead_with_scale_language"
    return "default_grounded"
