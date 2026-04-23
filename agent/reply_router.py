"""Central reply router — the interface webhook handlers hand inbound events to.

Downstream code attaches handlers via `register(...)`. The router is intentionally
thin: it keeps the webhook layer free of business logic and gives every channel
one place to look when it needs to fire a follow-up action.

Public surface:
    register_email_reply_handler(fn)
    register_sms_inbound_handler(fn)
    register_booking_handler(fn)
    dispatch_email_reply(event)   -- called from webhooks
    dispatch_sms_inbound(event)
    dispatch_booking(event)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event dataclasses (frozen) — what handlers receive
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EmailReplyEvent:
    thread_id: str
    from_address: str
    subject: str
    body_text: str
    received_at: datetime
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SMSInboundEvent:
    from_number: str
    to_shortcode: str
    body: str
    received_at: datetime
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BookingEvent:
    booking_uid: str
    attendee_email: str
    start_time: datetime
    status: str  # "created" | "cancelled" | "rescheduled"
    prospect_domain: str | None
    raw: dict = field(default_factory=dict)


class EmailReplyHandler(Protocol):
    def __call__(self, event: EmailReplyEvent) -> None: ...


class SMSInboundHandler(Protocol):
    def __call__(self, event: SMSInboundEvent) -> None: ...


class BookingHandler(Protocol):
    def __call__(self, event: BookingEvent) -> None: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_email_handlers: list[EmailReplyHandler] = []
_sms_handlers: list[SMSInboundHandler] = []
_booking_handlers: list[BookingHandler] = []

# Replied-by-email prospects — the gate for SMS outbound. A prospect must have
# replied at least once on email before any SMS is allowed. This matches the
# Tenacious channel hierarchy: email primary, SMS secondary for warm leads.
_warm_prospects: set[str] = set()


def register_email_reply_handler(fn: EmailReplyHandler) -> None:
    _email_handlers.append(fn)


def register_sms_inbound_handler(fn: SMSInboundHandler) -> None:
    _sms_handlers.append(fn)


def register_booking_handler(fn: BookingHandler) -> None:
    _booking_handlers.append(fn)


def mark_warm(prospect_key: str) -> None:
    """Promote a prospect to warm status (allowed to receive SMS)."""
    _warm_prospects.add(prospect_key.lower())


def is_warm(prospect_key: str) -> bool:
    return prospect_key.lower() in _warm_prospects


def _reset_for_tests() -> None:
    _email_handlers.clear()
    _sms_handlers.clear()
    _booking_handlers.clear()
    _warm_prospects.clear()


# ---------------------------------------------------------------------------
# Dispatchers — called from agent/webhook.py
# ---------------------------------------------------------------------------

def dispatch_email_reply(event: EmailReplyEvent) -> None:
    # Any email reply promotes the sender to warm — SMS now permitted.
    mark_warm(event.from_address)
    _fanout(_email_handlers, event, label="email_reply")


def dispatch_sms_inbound(event: SMSInboundEvent) -> None:
    _fanout(_sms_handlers, event, label="sms_inbound")


def dispatch_booking(event: BookingEvent) -> None:
    _fanout(_booking_handlers, event, label="booking")


def _fanout(handlers: list[Callable], event, *, label: str) -> None:
    if not handlers:
        log.info("reply_router: no handler registered for %s, event dropped", label)
        return
    for fn in handlers:
        try:
            fn(event)
        except Exception:
            # One misbehaving handler must not block the others. Log and continue.
            log.exception("reply_router: handler for %s raised; continuing", label)


# ---------------------------------------------------------------------------
# Parsing helpers — turn raw webhook payloads into dataclasses
# ---------------------------------------------------------------------------

def parse_resend_reply(payload: dict) -> EmailReplyEvent | None:
    """Parse a Resend `email.replied` payload. Returns None for other event types
    or malformed payloads — callers must treat None as 'nothing to dispatch'."""
    if payload.get("type") != "email.replied":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        log.warning("reply_router: resend reply payload missing 'data'")
        return None
    headers = data.get("headers") or {}
    try:
        return EmailReplyEvent(
            thread_id=str(headers.get("x-thread-id") or data.get("email_id") or ""),
            from_address=str(data.get("from") or ""),
            subject=str(data.get("subject") or ""),
            body_text=str(data.get("text") or ""),
            received_at=_parse_iso(data.get("created_at")),
            raw=payload,
        )
    except (KeyError, TypeError, ValueError):
        log.warning("reply_router: malformed resend reply payload")
        return None


def parse_at_inbound(form: dict) -> SMSInboundEvent | None:
    """Parse an Africa's Talking inbound SMS form payload."""
    if form.get("messageType") != "Inbound":
        return None
    from_number = str(form.get("from") or "")
    if not from_number:
        log.warning("reply_router: AT inbound without 'from' field")
        return None
    return SMSInboundEvent(
        from_number=from_number,
        to_shortcode=str(form.get("to") or ""),
        body=str(form.get("text") or ""),
        received_at=_parse_iso(form.get("date")) or datetime.now(timezone.utc),
        raw=dict(form),
    )


def parse_calcom_booking(payload: dict) -> BookingEvent | None:
    """Parse a Cal.com booking webhook payload."""
    trigger = payload.get("triggerEvent", "")
    status_map = {
        "BOOKING_CREATED": "created",
        "BOOKING_CANCELLED": "cancelled",
        "BOOKING_RESCHEDULED": "rescheduled",
    }
    if trigger not in status_map:
        return None

    inner = payload.get("payload") or {}
    attendees = inner.get("attendees") or [{}]
    first = attendees[0] if attendees else {}
    start = _parse_iso(inner.get("startTime"))
    if start is None:
        start = datetime.now(timezone.utc)
    return BookingEvent(
        booking_uid=str(inner.get("uid") or ""),
        attendee_email=str(first.get("email") or ""),
        start_time=start,
        status=status_map[trigger],
        prospect_domain=(first.get("email") or "").split("@")[-1] or None,
        raw=payload,
    )


def _parse_iso(value) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
