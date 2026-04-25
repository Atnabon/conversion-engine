"""Tests for the silent-company case in AI-maturity scoring."""
from agent.enrichment import ai_maturity


def test_empty_signal_list_returns_score_zero_and_silent_flag():
    result = ai_maturity.score([])
    assert result.score == 0
    assert result.silent_company is True
    assert result.silent_company_disclaimer is not None
    assert "absence is not proof of absence" in result.silent_company_disclaimer.lower()
    # The silent disclaimer is also surfaced in justifications so a
    # downstream consumer that only reads justifications still sees it.
    assert any(j["signal"] == "no_public_signal" for j in result.justifications)


def test_low_score_with_signals_is_not_silent():
    # Signals exist but score still rounds to 0 — this is NOT silent.
    signals = [
        ai_maturity.SignalInput("modern_data_ml_stack", "dbt only", "low", "low"),
    ]
    result = ai_maturity.score(signals)
    assert result.score == 0
    assert result.silent_company is False
    assert result.silent_company_disclaimer is None


def test_silent_company_disclaimer_mentions_segment_4_block():
    """The disclaimer must explicitly forbid Segment 4 pitch language."""
    result = ai_maturity.score([])
    assert "Segment 4" in result.silent_company_disclaimer
