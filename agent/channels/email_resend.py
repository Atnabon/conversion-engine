"""Outbound email handler using Resend.

This module is the single seam for outbound email. The kill-switch
(`TENACIOUS_LIVE_OUTREACH`) defaults to unset, in which case every send is
rewritten to the program-staff sink — no real prospect ever receives mail
during the challenge week.

Inbound replies land in `agent/webhook.py` → `POST /webhooks/resend`, are
parsed into an `EmailReplyEvent`, and dispatched to every handler registered
via `reply_router.register_email_reply_handler(...)`. Downstream code
(qualifier, composer, HubSpot writer) attaches to that seam instead of reaching
into the webhook module directly.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from agent import reply_router

log = logging.getLogger(__name__)


class _ResendTransport(Protocol):
    """Minimal protocol we depend on — lets tests inject a fake."""
    class Emails:
        @staticmethod
        def send(payload: dict) -> dict: ...


@dataclass(frozen=True)
class SendResult:
    ok: bool
    message_id: str | None
    routed_to: str
    error: str | None = None


class EmailSendError(RuntimeError):
    """Raised when Resend rejects a send and the caller needs to react.

    We expose this distinct from `SendResult` so a caller can either branch on
    the result envelope (preferred) or propagate via exception when wrapped in
    a broader retry loop.
    """


def _sink_active() -> bool:
    return os.getenv("TENACIOUS_LIVE_OUTREACH") != "true"


def _resolve_recipient(intended: str) -> str:
    """Route to staff sink whenever the kill-switch is unset."""
    if _sink_active():
        return os.getenv("STAFF_SINK_EMAIL", "sink@tenacious-program.test")
    return intended


def _configure() -> None:
    key = os.getenv("RESEND_API_KEY")
    if not key:
        raise EmailSendError("RESEND_API_KEY is not set")
    import resend  # lazy — optional dependency at module import time
    resend.api_key = key
    return resend


def _default_transport():
    import resend  # lazy import
    return resend


def send_email(
    *,
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    thread_id: str | None = None,
    transport: Any = None,
) -> SendResult:
    """Send outbound email via Resend.

    Failure paths:
    - Missing API key → `EmailSendError`.
    - Resend API error → caught and returned as `SendResult(ok=False, error=...)`.
    - Bounce/complaint events arrive later via the webhook; see `on_bounce`.
    """
    if transport is None:
        transport = _default_transport()
        _configure()

    from_addr = os.getenv("RESEND_FROM_ADDRESS") or "noreply@tenacious-program.test"
    routed_to = _resolve_recipient(to)
    payload: dict[str, Any] = {
        "from": from_addr,
        "to": [routed_to],
        "subject": subject,
        "text": body_text,
    }
    if body_html:
        payload["html"] = body_html
    if thread_id:
        payload["headers"] = {"X-Thread-Id": thread_id}

    try:
        result = transport.Emails.send(payload)
    except Exception as exc:
        log.exception("resend send failed to=%s", routed_to)
        return SendResult(ok=False, message_id=None, routed_to=routed_to, error=str(exc))

    message_id = (result or {}).get("id") if isinstance(result, dict) else None
    if not message_id:
        log.error("resend send returned no id: %r", result)
        return SendResult(
            ok=False,
            message_id=None,
            routed_to=routed_to,
            error="resend returned no id",
        )
    return SendResult(ok=True, message_id=message_id, routed_to=routed_to)


# ---------------------------------------------------------------------------
# Webhook event handlers — registered with reply_router by importers
# ---------------------------------------------------------------------------

def handle_inbound_webhook(payload: dict) -> bool:
    """Called from the FastAPI webhook route. Returns True if dispatched.

    Keeps the webhook route free of parsing knowledge. Malformed payloads are
    logged and swallowed with a False return — never re-raised, so we always
    ACK 200 to Resend and avoid redelivery storms.
    """
    try:
        event_type = payload.get("type", "")
        if event_type == "email.replied":
            event = reply_router.parse_resend_reply(payload)
            if event is None:
                return False
            reply_router.dispatch_email_reply(event)
            return True
        if event_type in {"email.bounced", "email.complained"}:
            return _on_negative_event(event_type, payload)
        log.info("resend event ignored type=%s", event_type)
        return False
    except Exception:
        log.exception("resend webhook handler blew up; swallowing to ACK 200")
        return False


def _on_negative_event(event_type: str, payload: dict) -> bool:
    data = payload.get("data") or {}
    to = data.get("to") or data.get("email") or "unknown"
    log.warning("resend negative event=%s to=%s", event_type, to)
    # The reply router does not currently accept bounce events as first-class
    # dispatchable objects — suppressing is the right default until a handler
    # needs them. When one does, add a BounceEvent + dispatcher here.
    return True


# Convenience for smoke test / Day-0 checklist
def smoke() -> None:
    addr = os.getenv("RESEND_FROM_ADDRESS", "noreply@tenacious-program.test")
    result = send_email(
        to=addr,
        subject="Conversion Engine smoke test",
        body_text="If you can read this, the Resend integration is live.",
    )
    print(f"smoke: ok={result.ok} id={result.message_id} routed_to={result.routed_to}")


if __name__ == "__main__":
    smoke()
