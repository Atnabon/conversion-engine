import csv
import json
from datetime import date
from pathlib import Path

import pytest

from agent.enrichment import ai_maturity, crunchbase, job_posts, layoffs_fyi, leadership, pipeline


def _write_crunchbase(path: Path):
    path.write_text(
        "uuid,name,domain,categories,employee_count,country_code,last_funding_type,"
        "last_funding_total,last_funding_at,tech_stack\n"
        "cb-a1b2c3,Orrin Labs,orrin-labs.example,AI and Analytics,51-100,USA,"
        "series_b,14000000,2026-02-12,dbt,snowflake\n"
    )


def _write_layoffs(path: Path):
    path.write_text(
        "company,date,laid_off,percentage,source\n"
        "Orrin Labs,2026-03-10,40,0.12,https://layoffs.fyi/orrin-labs\n"
    )


def _write_snapshot(dir_path: Path, domain: str, roles: int = 4):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{domain}.json").write_text(
        json.dumps({"total_open_roles": roles, "ai_adjacent_open_roles": 1,
                    "sources": ["builtin"]})
    )


class _FakePlaywrightPage:
    def __init__(self, titles):
        self.titles = titles

    def goto(self, url, wait_until="domcontentloaded", timeout=15000):
        return None

    def evaluate(self, js):
        return self.titles

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self, titles):
        self.titles = titles

    def new_page(self, user_agent=None):
        return _FakePlaywrightPage(self.titles)

    def close(self):
        pass


class _FakeChromium:
    def __init__(self, titles):
        self.titles = titles

    def launch(self, headless=True):
        return _FakeBrowser(self.titles)


class _FakePlaywrightContext:
    def __init__(self, titles):
        self.chromium = _FakeChromium(titles)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_playwright_factory(titles):
    def make():
        return _FakePlaywrightContext(titles)
    return make


@pytest.fixture(autouse=True)
def _robots_allows_everything(monkeypatch):
    monkeypatch.setattr(job_posts, "_robots_allows", lambda url, user_agent="bot": True)


def test_ai_maturity_phrasing_hint_flags_low_confidence_high_score():
    sig = [
        ai_maturity.SignalInput("ai_adjacent_open_roles", "weak", "high", "low"),
        ai_maturity.SignalInput("executive_commentary", "one blog post", "medium", "low"),
    ]
    score = ai_maturity.score(sig)
    # Score will sit in 0-1 territory here; the key assertion is that the
    # hint function returns the ask-rather-than-assert hint when a
    # high-score-low-confidence combo happens — build one directly:
    assert ai_maturity.phrasing_hint(3, "low") == "ask_rather_than_assert"
    assert ai_maturity.phrasing_hint(0, "high") == "lead_with_stand_up_language"
    assert score.score <= 1


def test_leadership_detection_honors_window():
    items = [
        {
            "title": "Jane Doe joins Orrin Labs as Chief Technology Officer",
            "published_at": "2026-03-10",
            "url": "https://press.example/orrin-cto",
        }
    ]
    result = leadership.detect_from_news(
        news_items=items, today=date(2026, 4, 22), window_days=90
    )
    assert result.change.detected
    assert result.change.role == "cto"
    assert result.change.new_leader_name == "Jane Doe"


def test_leadership_ignores_old_appointments():
    items = [{
        "title": "Older CTO appointment",
        "published_at": "2025-10-01",
    }]
    result = leadership.detect_from_news(
        news_items=items, today=date(2026, 4, 22), window_days=90
    )
    assert result.change.detected is False


def test_layoffs_fyi_finds_within_window(tmp_path):
    csv_path = tmp_path / "layoffs.csv"
    _write_layoffs(csv_path)
    result = layoffs_fyi.lookup(
        prospect_name="Orrin Labs",
        today=date(2026, 4, 22),
        path=csv_path,
    )
    assert result.status == "success"
    assert result.event and result.event.headcount_reduction == 40


def test_layoffs_fyi_returns_no_event_when_outside_window(tmp_path):
    csv_path = tmp_path / "layoffs.csv"
    csv_path.write_text(
        "company,date,laid_off,percentage,source\n"
        "Orrin Labs,2025-10-01,10,0.05,https://layoffs.fyi/old\n"
    )
    result = layoffs_fyi.lookup(
        prospect_name="Orrin Labs",
        today=date(2026, 4, 22),
        path=csv_path,
    )
    assert result.event is None


def test_crunchbase_lookup_misses_gracefully(tmp_path):
    result = crunchbase.lookup("cb-unknown", path=tmp_path / "missing.csv")
    assert result.status == "no_data"
    assert result.record is None


def test_job_posts_refuses_login_urls():
    result = job_posts.scrape(
        prospect_domain="example.test",
        builtin_url="https://builtin.com/login",
    )
    assert result.status == "error"
    assert "login-adjacent" in (result.error or "")


def test_pipeline_produces_schema_shape(tmp_path, monkeypatch):
    cb_path = tmp_path / "cb.csv"
    _write_crunchbase(cb_path)
    layoffs_path = tmp_path / "layoffs.csv"
    layoffs_path.write_text("company,date,laid_off,percentage,source\n")
    snapshot_dir = tmp_path / "snapshots"
    _write_snapshot(snapshot_dir, "orrin-labs.example", roles=4)

    monkeypatch.setenv("CRUNCHBASE_ODM_PATH", str(cb_path))
    monkeypatch.setenv("LAYOFFS_FYI_CSV_PATH", str(layoffs_path))
    monkeypatch.setenv("JOB_POST_SNAPSHOT_DIR", str(snapshot_dir))

    # 11 titles, 3 of which contain AI-adjacent keywords.
    titles = [
        "Senior Python Engineer",
        "Data Platform Engineer",
        "ML Engineer",
        "Applied Scientist",
        "Backend Engineer",
        "Frontend Engineer",
        "Staff Engineer",
        "SRE",
        "Product Manager",
        "Recruiter",
        "QA Engineer",
    ]

    brief = pipeline.run(
        prospect_name="Orrin Labs",
        prospect_domain="orrin-labs.example",
        crunchbase_id="cb-a1b2c3",
        builtin_url="https://builtin.com/company/orrin-labs/jobs",
        news_items=[{
            "title": "Jane Doe joins Orrin Labs as Chief Technology Officer",
            "published_at": "2026-03-10",
        }],
        named_ai_leadership=False,
        github_org_has_ai_repos=False,
        executive_commentary_source_url="https://orrin-labs.example/blog/2026-roadmap",
        playwright_factory=_fake_playwright_factory(titles),
    )

    required_top = {
        "prospect_domain", "prospect_name", "generated_at",
        "primary_segment_match", "segment_confidence",
        "ai_maturity", "hiring_velocity", "buying_window_signals",
        "data_sources_checked",
    }
    assert required_top <= set(brief.keys())

    # Leadership change wins segment classification.
    assert brief["primary_segment_match"] == "segment_3_leadership_transition"

    # Every source records a status — this is the confidence-per-signal surface.
    sources_seen = {s["source"] for s in brief["data_sources_checked"]}
    assert sources_seen == {
        "crunchbase_odm", "public_job_posts", "layoffs_fyi", "leadership_news",
    }

    # AI maturity section carries both score and confidence.
    ai = brief["ai_maturity"]
    assert 0 <= ai["score"] <= 3
    assert ai["confidence_label"] in {"low", "medium", "high"}
    assert ai["phrasing_hint"] in {
        "ask_rather_than_assert",
        "lead_with_stand_up_language",
        "lead_with_scale_language",
        "default_grounded",
    }
