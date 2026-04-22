"""Conversion Engine orchestrator.

Flow:
    1. Load Crunchbase-seeded prospect.
    2. Run enrichment pipeline (parallel fan-out) -> hiring_signal_brief + competitor_gap_brief.
    3. ICP classifier with abstention -> segment + confidence.
    4. Pitch selector: segment x AI-maturity -> pitch variant.
    5. Draft composer -> tone check -> bench guard.
    6. Send via email (primary) or SMS (warm-lead scheduling).
    7. Handle reply webhook -> qualify -> Cal.com booking -> HubSpot upsert.
    8. Emit Langfuse trace with per-signal confidence + cost.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Segment = Literal[1, 2, 3, 4]


@dataclass(frozen=True)
class ProspectContext:
    crunchbase_id: str
    hiring_signal_brief: dict
    competitor_gap_brief: dict
    icp_segment: Segment | None
    icp_confidence: float
    ai_maturity: int
    ai_maturity_confidence: Literal["low", "medium", "high"]


def run(crunchbase_id: str) -> None:
    """Happy-path orchestrator. Real implementation spread across modules."""
    if os.getenv("TENACIOUS_LIVE_OUTREACH") != "true":
        # Kill-switch default: route all outbound to staff sink.
        os.environ["OUTBOUND_SINK"] = os.environ["STAFF_SINK_EMAIL"]
    # ... enrichment, ICP, pitch, compose, tone check, bench guard, send, trace
    raise NotImplementedError("Skeleton for interim submission — full flow tracked in traces.")


if __name__ == "__main__":
    import sys

    run(sys.argv[1] if len(sys.argv) > 1 else "cb-a1b2c3")
