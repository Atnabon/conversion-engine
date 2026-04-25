"""Tests for agent/composer.py — the seam where channels + HubSpot + Cal.com meet.

These tests assert the rubric requirements directly:
  - HubSpot writes occur at multiple conversation event points
  - Cal.com link generation is referenced from BOTH email and SMS handlers
  - SMS path enforces the warm-lead gate
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent import composer, reply_router
from agent.channels import email_resend, sms_at
from agent.tools import hubspot_mcp


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reply_router._reset_for_tests()
    monkeypatch.delenv("TENACIOUS_LIVE_OUTREACH", raising=False)
    monkeypatch.setenv("STAFF_SINK_EMAIL", "sink@tenacious-program.test")
    monkeypatch.setenv("STAFF_SINK_PHONE", "+251900000000")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "onboarding@resend.dev")
    monkeypatch.setenv("CALCOM_BASE_URL", "http://localhost:3000")
    yield
    reply_router._reset_for_tests()


def _brief():
    return {
        "prospect_domain": "orrin-labs.example",
        "prospect_name": "Orrin Labs",
        "generated_at": "2026-04-25T10:00:00Z",
        "primary_segment_match": "segment_3_leadership_transition",
        "segment_confidence": 0.87,
        "ai_maturity": {"score": 2, "confidence_label": "high"},
        "hiring_velocity": {"velocity_label": "doubled"},
        "buying_window_signals": {
            "funding_event": {"detected": True, "stage": "series_b"},
            "layoff_event": {"detected": False},
            "leadership_change": {"detected": True, "role": "cto"},
        },
        "bench_to_brief_match": {"bench_available": True},
        "honesty_flags": [],
    }


def _capture_hubspot(monkeypatch):
    captured: list[dict] = []

    def fake_upsert(write, *, client=None):
        captured.append({"contract": "upsert", "email": write.email,
                         "icp_segment": write.icp_segment,
                         "ai_maturity_score": write.ai_maturity_score})
        return {"id": f"hsa_{len(captured):03d}", "activity_id": f"hsa_{len(captured):03d}"}

    monkeypatch.setattr(hubspot_mcp, "upsert_contact_via_mcp", fake_upsert)
    return captured


def _fake_email_transport(ok=True, message_id="r-1"):
    class _FakeEmails:
        def __init__(self):
            self.last_payload = None
        def send(self, payload):
            self.last_payload = payload
            if ok:
                return {"id": message_id}
            raise RuntimeError("simulated send failure")
    class _T:
        Emails = _FakeEmails()
    return _T()


# ---------------------------------------------------------------------------
# HubSpot writes occur at multiple conversation event points
# ---------------------------------------------------------------------------

def test_email_outreach_writes_hubspot_at_three_points(monkeypatch):
    """outreach prepared + slots proposed + send result = 3 HubSpot writes."""
    captured = _capture_hubspot(monkeypatch)
    transport = _fake_email_transport()

    monkeypatch.setattr(email_resend, "send_email", lambda **kw: email_resend.SendResult(
        ok=True, message_id="r-42", routed_to=kw["to"],
    ))

    result = composer.compose_outreach_with_slots(
        contact_email="prospect@orrin-labs.example",
        contact_name="Pat Prospect",
        brief=_brief(),
        body_text="Hello — research finding...",
        subject="Request: 15 minutes",
    )

    assert result.sent
    assert result.booking_link and "discovery-call" in result.booking_link
    # Three activity writes: outreach prepared, slots proposed, outreach sent.
    assert len(captured) == 3
    # The brief-bearing writes (1st and 3rd) carry the right segment;
    # the slots_proposed write in the middle has no brief and defaults to abstain.
    assert captured[0]["icp_segment"] == "segment_3_leadership_transition"
    assert captured[2]["icp_segment"] == "segment_3_leadership_transition"


def test_failed_email_send_logs_outreach_failed_event(monkeypatch):
    captured = _capture_hubspot(monkeypatch)
    monkeypatch.setattr(email_resend, "send_email", lambda **kw: email_resend.SendResult(
        ok=False, message_id=None, routed_to=kw["to"], error="simulated 4xx",
    ))

    result = composer.compose_outreach_with_slots(
        contact_email="prospect@orrin-labs.example",
        contact_name="Pat Prospect",
        brief=_brief(),
        body_text="hi",
        subject="Request",
        propose_slots=False,  # skip slot proposal, simpler trace
    )

    assert result.sent is False
    # outreach prepared + outreach failed = 2 writes.
    assert len(captured) == 2


# ---------------------------------------------------------------------------
# Cal.com link generation is referenced from BOTH email and SMS handlers
# ---------------------------------------------------------------------------

def test_email_path_calls_propose_booking_slots(monkeypatch):
    _capture_hubspot(monkeypatch)
    monkeypatch.setattr(email_resend, "send_email", lambda **kw: email_resend.SendResult(
        ok=True, message_id="r-1", routed_to=kw["to"],
    ))

    proposed: list[str] = []
    real = composer.propose_booking_slots
    def spy(**kw):
        proposed.append(kw["contact_email"])
        return real(**kw)
    monkeypatch.setattr(composer, "propose_booking_slots", spy)

    result = composer.compose_outreach_with_slots(
        contact_email="a@example.test",
        contact_name="A B",
        brief=_brief(),
        body_text="hi",
        subject="s",
    )
    assert proposed == ["a@example.test"]
    assert "discovery-call" in (result.body_text or "")


def test_sms_path_calls_propose_booking_slots(monkeypatch):
    _capture_hubspot(monkeypatch)
    reply_router.mark_warm("a@example.test")

    class _FakeSMS:
        def send(self, **kw):
            return {"SMSMessageData": {"Recipients": [
                {"status": "Success", "messageId": "at-1", "cost": "KES 0.8"}
            ]}}

    monkeypatch.setattr(sms_at, "_configure", lambda: type("X", (), {"SMS": _FakeSMS()})())

    proposed: list[str] = []
    real = composer.propose_booking_slots
    def spy(**kw):
        proposed.append(kw["contact_email"])
        return real(**kw)
    monkeypatch.setattr(composer, "propose_booking_slots", spy)

    result = composer.compose_sms_warm_followup(
        contact_email="a@example.test",
        contact_phone="+15551234",
        contact_name="A B",
        brief=_brief(),
    )
    assert proposed == ["a@example.test"]
    assert result.booking_link is not None
    assert "discovery-call" in (result.booking_link or "")


# ---------------------------------------------------------------------------
# SMS path enforces the warm-lead gate
# ---------------------------------------------------------------------------

def test_sms_path_blocks_cold_prospect_and_logs(monkeypatch):
    captured = _capture_hubspot(monkeypatch)
    # Do NOT mark warm; the gate should fire.
    result = composer.compose_sms_warm_followup(
        contact_email="cold@example.test",
        contact_phone="+15551234",
        contact_name="Cold Lead",
        brief=_brief(),
    )
    assert result.sent is False
    assert result.error and "SMS blocked" in result.error
    # slots_proposed (always fires before the gate) + cold_sms_blocked.
    assert len(captured) == 2


# ---------------------------------------------------------------------------
# Reply handler logs to HubSpot
# ---------------------------------------------------------------------------

def test_reply_handler_writes_hubspot_activity(monkeypatch):
    captured = _capture_hubspot(monkeypatch)
    composer.register()

    reply_router.dispatch_email_reply(reply_router.EmailReplyEvent(
        thread_id="th-1",
        from_address="prospect@orrin-labs.example",
        subject="Re: Request",
        body_text="yes",
        received_at=datetime.now(timezone.utc),
    ))
    assert len(captured) == 1
    assert captured[0]["email"] == "prospect@orrin-labs.example"
