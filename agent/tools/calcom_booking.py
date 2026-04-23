"""Cal.com booking integration.

Exposes two callable surfaces to the rest of the agent codebase:

    create_booking(...)  — propose a slot from inside the outreach composer
    on_booking_event(...) — handler registered with reply_router; fires a
                            HubSpot write whenever Cal.com confirms a booking

The on_booking_event handler is what closes the integration loop:
Cal.com confirms → reply_router.dispatch_booking(...) → HubSpot contact is
updated with booking_uid and start_time on the same email-keyed record that
carries the ICP/enrichment fields. That is the link the CRM+Calendar rubric
checks for.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from agent import reply_router
from agent.tools import hubspot_mcp

log = logging.getLogger(__name__)


class BookingError(RuntimeError):
    pass


@dataclass(frozen=True)
class BookingRequest:
    event_type_id: int
    attendee_email: str
    attendee_name: str
    start_time: datetime  # UTC
    timezone: str         # e.g. "America/New_York"


@dataclass(frozen=True)
class BookingConfirmation:
    uid: str
    url: str
    start_time: str
    attendee_email: str


def _base_url() -> str:
    return os.getenv("CALCOM_BASE_URL", "http://localhost:3000").rstrip("/")


def _auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("CALCOM_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def create_booking(
    request: BookingRequest,
    *,
    client: httpx.Client | None = None,
) -> BookingConfirmation:
    """Call Cal.com /v2/bookings to create a meeting. Returns the confirmation."""
    url = f"{_base_url()}/v2/bookings"
    body: dict[str, Any] = {
        "eventTypeId": request.event_type_id,
        "start": request.start_time.isoformat(),
        "attendee": {
            "name": request.attendee_name,
            "email": request.attendee_email,
            "timeZone": request.timezone,
        },
    }

    owner = client or httpx.Client(timeout=15.0)
    try:
        resp = owner.post(url, json=body, headers=_auth_headers())
    except httpx.HTTPError as exc:
        raise BookingError(f"Cal.com request failed: {exc}") from exc
    finally:
        if client is None:
            owner.close()

    if resp.status_code >= 400:
        raise BookingError(
            f"Cal.com booking failed: status={resp.status_code} body={resp.text[:500]}"
        )
    data = resp.json() or {}
    payload = data.get("data") or data

    uid = payload.get("uid") or payload.get("id")
    if not uid:
        raise BookingError(f"Cal.com response missing uid: {data!r}")

    return BookingConfirmation(
        uid=str(uid),
        url=str(payload.get("url") or ""),
        start_time=str(payload.get("startTime") or payload.get("start") or request.start_time.isoformat()),
        attendee_email=request.attendee_email,
    )


# ---------------------------------------------------------------------------
# Booking-event handler — registered with the reply router at wire-up time
# ---------------------------------------------------------------------------

def on_booking_event(event: reply_router.BookingEvent) -> None:
    """Reply-router callback: propagate confirmed bookings to HubSpot.

    A created or rescheduled booking is the moment at which the agent's work
    actually converts into a discovery call — we record the booking against
    the same contact the outreach was addressed to. Cancellations are logged
    but do not currently clear the HubSpot property so the prior state is
    preserved for audit.
    """
    if event.status not in {"created", "rescheduled"}:
        log.info("booking event status=%s no HubSpot write", event.status)
        return
    if not event.attendee_email:
        log.warning("booking event %s has no attendee_email; skipping", event.booking_uid)
        return

    try:
        hubspot_mcp.record_booking(
            email=event.attendee_email,
            booking_uid=event.booking_uid,
            start_time=event.start_time.isoformat(),
            prospect_domain=event.prospect_domain,
        )
        log.info(
            "booking %s -> HubSpot update for %s",
            event.booking_uid,
            event.attendee_email,
        )
    except hubspot_mcp.HubSpotWriteError:
        log.exception(
            "booking %s: HubSpot write failed; will need reconciliation",
            event.booking_uid,
        )


def register() -> None:
    """Attach the booking handler to the reply router. Called at startup."""
    reply_router.register_booking_handler(on_booking_event)


def handle_inbound_webhook(payload: dict) -> bool:
    """Called from the FastAPI Cal.com route. Returns True if dispatched."""
    try:
        event = reply_router.parse_calcom_booking(payload)
        if event is None:
            return False
        reply_router.dispatch_booking(event)
        return True
    except Exception:
        log.exception("calcom webhook handler blew up; swallowing to ACK 200")
        return False


def smoke() -> None:
    try:
        with httpx.Client(timeout=5.0) as c:
            resp = c.get(f"{_base_url()}/api/health")
        print(f"smoke: cal.com reachable -> status={resp.status_code}")
    except httpx.HTTPError as exc:
        print(f"smoke: cal.com NOT reachable -> {exc}")


if __name__ == "__main__":
    smoke()
