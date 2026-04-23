from datetime import datetime, timezone

from agent import reply_router
from agent.tools import calcom_booking, hubspot_mcp


def test_contact_write_from_brief_populates_enrichment_fields():
    brief = {
        "prospect_name": "Orrin Labs",
        "prospect_domain": "orrin-labs.example",
        "primary_segment_match": "segment_1_series_a_b",
        "segment_confidence": 0.82,
        "generated_at": "2026-04-22T10:00:00Z",
        "ai_maturity": {"score": 2, "confidence_label": "medium"},
        "hiring_velocity": {"velocity_label": "doubled"},
        "buying_window_signals": {
            "funding_event": {"detected": True, "stage": "series_b"},
            "layoff_event": {"detected": False},
            "leadership_change": {"detected": False},
        },
        "bench_to_brief_match": {"bench_available": True},
        "honesty_flags": ["tech_stack_inferred_not_confirmed"],
    }
    write = hubspot_mcp.contact_write_from_brief(
        email="p@orrin-labs.example",
        firstname="Pat",
        lastname="P",
        brief=brief,
        crunchbase_id="cb-a1b2c3",
    )
    assert write.icp_segment == "segment_1_series_a_b"
    assert write.ai_maturity_score == 2
    assert write.ai_maturity_confidence == "medium"
    assert write.enrichment_timestamp == "2026-04-22T10:00:00Z"
    assert write.honesty_flags == ["tech_stack_inferred_not_confirmed"]


def test_booking_event_triggers_hubspot_write(monkeypatch):
    reply_router._reset_for_tests()
    calcom_booking.register()  # attach the handler

    captured: dict = {}

    def fake_record(*, email, booking_uid, start_time, prospect_domain, client=None):
        captured.update(
            email=email,
            booking_uid=booking_uid,
            start_time=start_time,
            prospect_domain=prospect_domain,
        )
        return {"ok": True}

    monkeypatch.setattr(hubspot_mcp, "record_booking", fake_record)

    reply_router.dispatch_booking(reply_router.BookingEvent(
        booking_uid="b-1",
        attendee_email="p@orrin-labs.example",
        start_time=datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc),
        status="created",
        prospect_domain="orrin-labs.example",
    ))

    assert captured == {
        "email": "p@orrin-labs.example",
        "booking_uid": "b-1",
        "start_time": "2026-04-25T15:00:00+00:00",
        "prospect_domain": "orrin-labs.example",
    }
    reply_router._reset_for_tests()


def test_cancelled_booking_does_not_write_hubspot(monkeypatch):
    reply_router._reset_for_tests()
    calcom_booking.register()

    called = {"n": 0}

    def fake_record(**kwargs):
        called["n"] += 1

    monkeypatch.setattr(hubspot_mcp, "record_booking", fake_record)

    reply_router.dispatch_booking(reply_router.BookingEvent(
        booking_uid="b-2",
        attendee_email="p@orrin-labs.example",
        start_time=datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc),
        status="cancelled",
        prospect_domain="orrin-labs.example",
    ))
    assert called["n"] == 0
    reply_router._reset_for_tests()
