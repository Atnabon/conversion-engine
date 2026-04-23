"""Outbound + inbound SMS handler using Africa's Talking.

Channel hierarchy (spec-level constraint):

    Email is primary. SMS is secondary and only used once a prospect has
    replied by email at least once — i.e. the prospect is warm. A cold SMS
    to a Tenacious prospect (founders, CTOs, VPs Eng) is out of policy and
    will be caught by `send_warm_sms` raising `ColdOutreachBlocked`.

The kill-switch gates real delivery: when `TENACIOUS_LIVE_OUTREACH` is unset,
every outbound SMS is routed to `STAFF_SINK_PHONE` instead of the intended
recipient. Inbound SMS events arrive at `webhook.py` → `POST /webhooks/at`,
are parsed into `SMSInboundEvent`, and dispatched via `reply_router`.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from agent import reply_router

log = logging.getLogger(__name__)


class ColdOutreachBlocked(RuntimeError):
    """Raised when SMS is attempted for a prospect that has not replied by email."""


class SMSSendError(RuntimeError):
    """Raised when AT rejects a send or is misconfigured."""


@dataclass(frozen=True)
class SMSSendResult:
    ok: bool
    message_id: str | None
    routed_to: str
    status: str
    cost: str | None = None
    error: str | None = None


_initialized = False


def _configure():
    global _initialized
    import africastalking  # lazy — optional dependency at module import time
    if _initialized:
        return africastalking
    username = os.getenv("AT_USERNAME")
    api_key = os.getenv("AT_API_KEY")
    if not username or not api_key:
        raise SMSSendError("AT_USERNAME / AT_API_KEY not set")
    africastalking.initialize(username, api_key)
    _initialized = True
    return africastalking


def _sink_active() -> bool:
    return os.getenv("TENACIOUS_LIVE_OUTREACH") != "true"


def _resolve_recipient(intended: str) -> str:
    if _sink_active():
        return os.getenv("STAFF_SINK_PHONE", "+251900000000")
    return intended


def send_warm_sms(
    *,
    to_number: str,
    body: str,
    prospect_key: str,
    transport: Any | None = None,
) -> SMSSendResult:
    """Send an SMS to a warm prospect.

    A prospect is warm iff they have replied by email at least once — the
    reply router records this in `_warm_prospects` via `mark_warm`. Calling
    this function for a cold prospect raises `ColdOutreachBlocked`.

    `prospect_key` is typically the prospect's email address so the warm
    check aligns with the identifier `reply_router.mark_warm` records when
    an inbound email reply arrives.
    """
    if not reply_router.is_warm(prospect_key):
        raise ColdOutreachBlocked(
            f"SMS blocked: prospect {prospect_key!r} has not replied by email. "
            "SMS is a warm-lead channel only (see agent/channels/sms_at.py)."
        )

    service = transport
    if service is None:
        at = _configure()
        service = at.SMS

    shortcode = os.getenv("AT_SHORTCODE") or None
    routed_to = _resolve_recipient(to_number)

    try:
        kwargs: dict[str, Any] = {"message": body, "recipients": [routed_to]}
        if shortcode:
            kwargs["sender_id"] = shortcode
        response = service.send(**kwargs)
    except Exception as exc:
        log.exception("AT send failed to=%s", routed_to)
        return SMSSendResult(
            ok=False,
            message_id=None,
            routed_to=routed_to,
            status="error",
            error=str(exc),
        )

    recipients = (response or {}).get("SMSMessageData", {}).get("Recipients", [])
    if not recipients:
        return SMSSendResult(
            ok=False,
            message_id=None,
            routed_to=routed_to,
            status="no_recipients",
            error="AT response had no Recipients",
        )
    r = recipients[0]
    status_val = str(r.get("status", ""))
    ok = status_val.lower() in {"success", "sent"}
    return SMSSendResult(
        ok=ok,
        message_id=r.get("messageId"),
        routed_to=routed_to,
        status=status_val,
        cost=r.get("cost"),
        error=None if ok else status_val,
    )


# NOTE: there is intentionally no `send_cold_sms`. SMS on cold outreach is
# out of policy for Tenacious. If a future segment extension needs SMS-first
# outreach, add a new entrypoint with its own gate rather than relaxing this
# one — make the channel-hierarchy decision explicit.


# ---------------------------------------------------------------------------
# Inbound webhook adapter
# ---------------------------------------------------------------------------

def handle_inbound_webhook(form: dict) -> bool:
    """Adapter for the FastAPI route. Returns True if an event was dispatched.

    Any delivery report that comes back with a failure status is logged as a
    negative signal but is not currently dispatched — callers that need to
    react to failed deliveries can subscribe to a future delivery-report seam.
    """
    try:
        message_type = str(form.get("messageType", ""))
        if message_type == "Inbound":
            event = reply_router.parse_at_inbound(dict(form))
            if event is None:
                return False
            reply_router.dispatch_sms_inbound(event)
            return True
        if message_type == "DeliveryReport":
            status_val = str(form.get("status", ""))
            failed = status_val.lower() not in {"success", "sent", "buffered"}
            if failed:
                log.warning(
                    "AT delivery report failure status=%s to=%s",
                    status_val,
                    form.get("phoneNumber"),
                )
            return True
        log.info("AT event ignored messageType=%s", message_type)
        return False
    except Exception:
        log.exception("AT webhook handler blew up; swallowing to ACK 200")
        return False


def smoke() -> None:
    sink = os.getenv("STAFF_SINK_PHONE", "+251900000000")
    # Promote the sink to warm so the smoke test does not trip the cold block.
    reply_router.mark_warm(sink)
    result = send_warm_sms(
        to_number=sink,
        body="Conversion Engine SMS smoke test",
        prospect_key=sink,
    )
    print(f"smoke: ok={result.ok} id={result.message_id} routed_to={result.routed_to}")


if __name__ == "__main__":
    smoke()
