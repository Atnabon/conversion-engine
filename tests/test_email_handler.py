import pytest

from agent import reply_router
from agent.channels import email_resend


class _FakeResendEmails:
    _SENTINEL = object()

    def __init__(self, result=_SENTINEL, exc=None):
        self.result = {"id": "r-1"} if result is _FakeResendEmails._SENTINEL else result
        self.exc = exc
        self.last_payload = None

    def send(self, payload):
        self.last_payload = payload
        if self.exc is not None:
            raise self.exc
        return self.result


class _FakeResendTransport:
    def __init__(self, emails):
        self.Emails = emails


@pytest.fixture(autouse=True)
def _isolate_router():
    reply_router._reset_for_tests()
    yield
    reply_router._reset_for_tests()


@pytest.fixture(autouse=True)
def _kill_switch(monkeypatch):
    monkeypatch.delenv("TENACIOUS_LIVE_OUTREACH", raising=False)
    monkeypatch.setenv("STAFF_SINK_EMAIL", "sink@tenacious-program.test")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "noreply@tenacious-program.test")


def test_send_routes_to_sink_when_kill_switch_unset():
    emails = _FakeResendEmails(result={"id": "r-42"})
    result = email_resend.send_email(
        to="prospect@example.test",
        subject="Request: 15 minutes",
        body_text="hi",
        transport=_FakeResendTransport(emails),
    )
    assert result.ok and result.message_id == "r-42"
    assert result.routed_to == "sink@tenacious-program.test"
    assert emails.last_payload["to"] == ["sink@tenacious-program.test"]


def test_send_returns_error_envelope_when_transport_raises():
    emails = _FakeResendEmails(exc=RuntimeError("rate limited"))
    result = email_resend.send_email(
        to="prospect@example.test",
        subject="Request",
        body_text="hi",
        transport=_FakeResendTransport(emails),
    )
    assert result.ok is False
    assert "rate limited" in (result.error or "")


def test_send_returns_error_when_api_omits_id():
    emails = _FakeResendEmails(result={})
    result = email_resend.send_email(
        to="prospect@example.test",
        subject="Request",
        body_text="hi",
        transport=_FakeResendTransport(emails),
    )
    assert result.ok is False
    assert "no id" in (result.error or "")


def test_inbound_webhook_dispatches_reply_event():
    hits: list[reply_router.EmailReplyEvent] = []
    reply_router.register_email_reply_handler(hits.append)

    payload = {
        "type": "email.replied",
        "data": {
            "from": "prospect@example.test",
            "subject": "Re: Request",
            "text": "Yes — Tuesday",
            "created_at": "2026-04-22T10:00:00Z",
            "headers": {"x-thread-id": "th-7"},
        },
    }
    dispatched = email_resend.handle_inbound_webhook(payload)
    assert dispatched is True
    assert hits and hits[0].thread_id == "th-7"
    assert reply_router.is_warm("prospect@example.test")


def test_bounce_event_is_logged_not_dispatched():
    hits = []
    reply_router.register_email_reply_handler(hits.append)
    dispatched = email_resend.handle_inbound_webhook({
        "type": "email.bounced",
        "data": {"to": "bad@example.test"},
    })
    assert dispatched is True
    assert hits == []


def test_malformed_payload_swallows_to_ack_200():
    # A non-dict payload should not raise; the webhook must ACK 200 to avoid
    # redelivery storms.
    assert email_resend.handle_inbound_webhook({"type": "email.replied", "data": None}) is False
