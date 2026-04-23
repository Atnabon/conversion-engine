from datetime import datetime, timezone

import pytest

from agent import reply_router
from agent.channels import sms_at


class _FakeATSms:
    def __init__(self, status="Success", message_id="at-1"):
        self.status = status
        self.message_id = message_id
        self.last_kwargs = None

    def send(self, **kwargs):
        self.last_kwargs = kwargs
        return {"SMSMessageData": {"Recipients": [
            {"status": self.status, "messageId": self.message_id, "cost": "KES 0.8000"}
        ]}}


@pytest.fixture(autouse=True)
def _isolate_router():
    reply_router._reset_for_tests()
    yield
    reply_router._reset_for_tests()


@pytest.fixture(autouse=True)
def _kill_switch(monkeypatch):
    # Default: sink active. Tests opt out explicitly.
    monkeypatch.delenv("TENACIOUS_LIVE_OUTREACH", raising=False)
    monkeypatch.setenv("STAFF_SINK_PHONE", "+251900000000")


def test_cold_sms_is_blocked():
    with pytest.raises(sms_at.ColdOutreachBlocked):
        sms_at.send_warm_sms(
            to_number="+15551234",
            body="test",
            prospect_key="cold@example.test",
            transport=_FakeATSms(),
        )


def test_warm_sms_routes_to_sink_when_kill_switch_unset():
    reply_router.mark_warm("warm@example.test")
    fake = _FakeATSms()
    result = sms_at.send_warm_sms(
        to_number="+15551234",
        body="test",
        prospect_key="warm@example.test",
        transport=fake,
    )
    assert result.ok
    assert result.routed_to == "+251900000000"
    assert fake.last_kwargs["recipients"] == ["+251900000000"]


def test_warm_sms_after_email_reply_promotes_then_sends():
    reply = reply_router.EmailReplyEvent(
        thread_id="t-3",
        from_address="prospect@example.test",
        subject="Re",
        body_text="yes",
        received_at=datetime.now(timezone.utc),
    )
    reply_router.dispatch_email_reply(reply)

    fake = _FakeATSms()
    result = sms_at.send_warm_sms(
        to_number="+15551234",
        body="picking a slot?",
        prospect_key="prospect@example.test",
        transport=fake,
    )
    assert result.ok


def test_inbound_sms_webhook_dispatches_to_handler():
    hits: list[reply_router.SMSInboundEvent] = []
    reply_router.register_sms_inbound_handler(hits.append)
    dispatched = sms_at.handle_inbound_webhook({
        "messageType": "Inbound",
        "from": "+15551234",
        "to": "TRX",
        "text": "10am tuesday works",
    })
    assert dispatched is True
    assert hits and hits[0].body == "10am tuesday works"


def test_inbound_delivery_report_is_not_dispatched_to_handlers():
    hits = []
    reply_router.register_sms_inbound_handler(hits.append)
    dispatched = sms_at.handle_inbound_webhook({
        "messageType": "DeliveryReport",
        "status": "Failed",
        "phoneNumber": "+15551234",
    })
    assert dispatched is True  # acknowledged
    assert hits == []
