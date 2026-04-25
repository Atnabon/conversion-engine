"""Tests for the competitor_gap peer-discovery + sparse-sector handling."""
from __future__ import annotations

from agent.enrichment import ai_maturity, competitor_gap


def _signals_for(row):
    """Stub scorer — yields one high-weight signal whose confidence is taken
    from the row's `ai_maturity_hint` field. Lets us drive deterministic peer
    scores from the test fixture."""
    hint = row.get("ai_maturity_hint", "low")
    yield ai_maturity.SignalInput(
        signal="ai_adjacent_open_roles",
        status=f"hint={hint}",
        weight="high",
        confidence=hint,
    )


def _candidate_pool():
    return [
        {"domain": "self.example", "name": "Prospect", "categories": "robotics", "headcount_band": "50-200", "ai_maturity_hint": "high"},
        {"domain": "alpha.example", "name": "Alpha", "categories": "robotics", "headcount_band": "50-200", "ai_maturity_hint": "high"},
        {"domain": "beta.example", "name": "Beta", "categories": "robotics", "headcount_band": "50-200", "ai_maturity_hint": "medium"},
        {"domain": "gamma.example", "name": "Gamma", "categories": "robotics", "headcount_band": "50-200", "ai_maturity_hint": "high"},
        {"domain": "delta.example", "name": "Delta", "categories": "robotics", "headcount_band": "50-200", "ai_maturity_hint": "medium"},
        {"domain": "epsilon.example", "name": "Epsilon", "categories": "robotics", "headcount_band": "50-200", "ai_maturity_hint": "low"},
        {"domain": "wrong-sector.example", "name": "WS", "categories": "fintech", "headcount_band": "50-200", "ai_maturity_hint": "high"},
        {"domain": "wrong-band.example", "name": "WB", "categories": "robotics", "headcount_band": "200-500", "ai_maturity_hint": "high"},
    ]


def test_discover_peers_excludes_prospect_and_filters_sector_and_band():
    peers = competitor_gap.discover_top_quartile_peers(
        prospect_domain="self.example",
        prospect_sector="robotics",
        prospect_headcount_band="50-200",
        candidate_pool=_candidate_pool(),
        score_signals_for=_signals_for,
    )
    domains = [p.domain for p in peers]
    # Prospect itself excluded.
    assert "self.example" not in domains
    # Wrong-sector and wrong-band candidates excluded.
    assert "wrong-sector.example" not in domains
    assert "wrong-band.example" not in domains
    # 5 valid peers remain.
    assert set(domains) == {
        "alpha.example", "beta.example", "gamma.example",
        "delta.example", "epsilon.example",
    }
    # Ranked by maturity score descending.
    scores = [p.ai_maturity_score for p in peers]
    assert scores == sorted(scores, reverse=True)


def test_discover_peers_caps_at_max():
    pool = [
        {"domain": f"peer-{i}.example", "name": f"P{i}", "categories": "robotics",
         "headcount_band": "50-200", "ai_maturity_hint": "high"}
        for i in range(20)
    ]
    peers = competitor_gap.discover_top_quartile_peers(
        prospect_domain="self.example",
        prospect_sector="robotics",
        prospect_headcount_band="50-200",
        candidate_pool=pool,
        score_signals_for=_signals_for,
    )
    assert len(peers) == competitor_gap.MAX_PEERS == 10


def test_distribution_position_below_top_quartile():
    peers = [
        competitor_gap.PeerCompany("X", f"x{i}.example", score=2 if i < 3 else 1,
                                    ai_maturity_justification=[],
                                    headcount_band="50-200", sources_checked=[])
        if False else competitor_gap.PeerCompany(
            name=f"X{i}", domain=f"x{i}.example",
            ai_maturity_score=(2 if i < 3 else 1),
            ai_maturity_justification=[], headcount_band="50-200",
            sources_checked=[])
        for i in range(8)
    ]
    pos = competitor_gap.compute_distribution_position(prospect_score=1, peers=peers)
    assert pos.n_peers_compared == 8
    assert pos.below_top_quartile is True
    assert pos.above_top_quartile is False
    assert 0.0 <= pos.percentile <= 1.0


def test_sparse_sector_returns_degraded_brief_without_raising():
    # Only 3 peers — below MIN_PEERS = 5.
    peers = [
        competitor_gap.PeerCompany(
            name=f"P{i}", domain=f"p{i}.example",
            ai_maturity_score=2,
            ai_maturity_justification=["high signal"],
            headcount_band="50-200", sources_checked=[])
        for i in range(3)
    ]
    brief = competitor_gap.build(
        prospect_domain="self.example",
        prospect_sector="niche-robotics",
        prospect_sub_niche=None,
        prospect_ai_maturity=1,
        peers=peers,
        practices=[],  # spec says practices required only when not sparse
    )
    assert brief["gap_quality_self_check"]["sparse_sector"] is True
    assert brief["gap_findings"] == []
    assert brief["gap_quality_self_check"]["n_peers_found"] == 3
    assert "Sparse sector" in brief["suggested_pitch_shift"]


def test_full_brief_round_trip():
    peers = [
        competitor_gap.PeerCompany(
            name=f"P{i}", domain=f"p{i}.example",
            ai_maturity_score=(3 if i < 2 else 2),
            ai_maturity_justification=["evidence"],
            headcount_band="50-200", sources_checked=["url"])
        for i in range(6)
    ]
    practice = competitor_gap.PracticeCandidate(
        practice="Named Head of AI on team page",
        peer_evidence=[
            {"competitor_name": "P0", "evidence": "team page", "source_url": "https://p0/team"},
            {"competitor_name": "P1", "evidence": "team page", "source_url": "https://p1/team"},
        ],
        prospect_state="No public Head of AI on team page",
        confidence="high",
        segment_relevance=["segment_4_specialized_capability"],
    )
    brief = competitor_gap.build(
        prospect_domain="self.example",
        prospect_sector="industrial-robotics",
        prospect_sub_niche="warehouse",
        prospect_ai_maturity=1,
        peers=peers,
        practices=[practice],
    )
    assert brief["gap_quality_self_check"]["sparse_sector"] is False
    assert brief["gap_quality_self_check"]["all_peer_evidence_has_source_url"] is True
    assert brief["gap_quality_self_check"]["at_least_one_gap_high_confidence"] is True
    assert "prospect_distribution_position" in brief
    assert brief["prospect_distribution_position"]["n_peers_compared"] == 6
