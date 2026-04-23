from datetime import datetime, timezone

import pytest

from agent import reply_router


@pytest.fixture(autouse=True)
def _isolate_router():
    reply_router._reset_for_tests()
    yield
    reply_router._reset_for_tests()


def test_email_reply_fanout_and_warm_promotion():
    received: list[reply_router.EmailReplyEvent] = []
    reply_router.register_email_reply_handler(received.append)

    event = reply_router.EmailReplyEvent(
        thread_id="t-1",
        from_address="prospect@example.test",
        subject="Re: Request",
        body_text="yes let's talk",
        received_at=datetime.now(timezone.utc),
    )
    reply_router.dispatch_email_reply(event)

    assert received == [event]
    assert reply_router.is_warm("prospect@example.test")
    assert not reply_router.is_warm("stranger@example.test")


def test_one_handler_raising_does_not_block_others():
    hits: list[str] = []

    def bad(event):
        raise RuntimeError("boom")

    def good(event):
        hits.append(event.from_address)

    reply_router.register_email_reply_handler(bad)
    reply_router.register_email_reply_handler(good)

    reply_router.dispatch_email_reply(
        reply_router.EmailReplyEvent(
            thread_id="t-2",
            from_address="p@example.test",
            subject="s",
            body_text="b",
            received_at=datetime.now(timezone.utc),
        )
    )
    assert hits == ["p@example.test"]


def test_parse_resend_reply_returns_none_on_wrong_type():
    assert reply_router.parse_resend_reply({"type": "email.sent", "data": {}}) is None


def test_parse_resend_reply_happy_path():
    payload = {
        "type": "email.replied",
        "data": {
            "from": "prospect@example.test",
            "subject": "Re: Request",
            "text": "yes",
            "created_at": "2026-04-22T10:00:00Z",
            "headers": {"x-thread-id": "th-7"},
        },
    }
    event = reply_router.parse_resend_reply(payload)
    assert event is not None
    assert event.thread_id == "th-7"
    assert event.from_address == "prospect@example.test"


def test_parse_at_inbound_requires_from_field():
    assert reply_router.parse_at_inbound({"messageType": "Inbound"}) is None
    event = reply_router.parse_at_inbound(
        {"messageType": "Inbound", "from": "+15551234", "text": "yes", "to": "TRX"}
    )
    assert event is not None
    assert event.from_number == "+15551234"


def test_parse_calcom_booking_event_statuses():
    created = reply_router.parse_calcom_booking({
        "triggerEvent": "BOOKING_CREATED",
        "payload": {
            "uid": "b-1",
            "startTime": "2026-04-25T15:00:00Z",
            "attendees": [{"email": "p@example.test"}],
        },
    })
    assert created and created.status == "created"
    assert reply_router.parse_calcom_booking({"triggerEvent": "BOOKING_STARTED"}) is None
