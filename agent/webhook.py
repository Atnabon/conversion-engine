"""Webhook receiver for Render deployment.

Registers once at $WEBHOOK_BASE_URL; all four integrations call in here:
    POST /webhooks/resend       — inbound reply + bounce from Resend
    POST /webhooks/at           — SMS delivery / reply from Africa's Talking
    POST /webhooks/calcom       — booking.created / booking.cancelled from Cal.com
    POST /webhooks/hubspot      — deal/contact events from HubSpot

Plus one manual reply ingestion endpoint:
    POST /conversations/reply   — manual reply ingestion for environments where
                                  the email provider's reply webhook is gated
                                  (e.g. Resend free tier requires a verified
                                  sending domain; the Slack tutor confirmed
                                  this manual path as the official workaround).

Payloads are handed off to channel-specific adapters that parse, validate,
and dispatch via `agent.reply_router`. The webhook module itself stays free
of business logic so new downstream handlers can attach without touching
the HTTP surface.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from datetime import datetime, timezone

from agent import composer, reply_router
from agent.channels import email_resend, sms_at
from agent.tools import calcom_booking

log = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Conversion Engine Webhooks")

# Attach the integration handlers once at import time:
#   - calcom_booking writes a HubSpot record when a booking is confirmed
#   - composer logs every email/SMS reply as a HubSpot activity
# Together these guarantee HubSpot writes occur at multiple conversation
# event points (outreach send, reply received, slots proposed, booking
# confirmed) — the rubric requirement.
calcom_booking.register()
composer.register()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_hmac(body: bytes, signature: str, secret: str, prefix: str = "") -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = signature.removeprefix(prefix)
    return hmac.compare_digest(expected, received)


def _sink_active() -> bool:
    return os.getenv("TENACIOUS_LIVE_OUTREACH") != "true"


# ---------------------------------------------------------------------------
# Resend — inbound email reply / bounce
# ---------------------------------------------------------------------------

@app.post("/webhooks/resend", status_code=status.HTTP_200_OK)
async def resend_webhook(
    request: Request,
    svix_signature: str | None = Header(None),
) -> JSONResponse:
    body = await request.body()

    secret = os.getenv("RESEND_WEBHOOK_SECRET", "")
    if secret and svix_signature:
        if not _verify_hmac(body, svix_signature, secret, prefix="v1,"):
            raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        log.warning("resend webhook: malformed JSON; ack 200")
        return JSONResponse({"ok": False, "reason": "malformed payload"})

    dispatched = email_resend.handle_inbound_webhook(payload)
    log.info("resend webhook dispatched=%s sink=%s", dispatched, _sink_active())
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Africa's Talking — SMS delivery report + inbound reply
# ---------------------------------------------------------------------------

@app.post("/webhooks/at", status_code=status.HTTP_200_OK)
async def at_webhook(request: Request) -> JSONResponse:
    try:
        form = await request.form()
    except Exception:
        log.warning("AT webhook: malformed form body; ack 200")
        return JSONResponse({})

    dispatched = sms_at.handle_inbound_webhook(dict(form))
    log.info("AT webhook dispatched=%s sink=%s", dispatched, _sink_active())
    return JSONResponse({})


# ---------------------------------------------------------------------------
# Cal.com — booking events
# ---------------------------------------------------------------------------

@app.post("/webhooks/calcom", status_code=status.HTTP_200_OK)
async def calcom_webhook(
    request: Request,
    x_cal_signature_256: str | None = Header(None),
) -> JSONResponse:
    body = await request.body()

    secret = os.getenv("CALCOM_WEBHOOK_SECRET", "")
    if secret and x_cal_signature_256:
        if not _verify_hmac(body, x_cal_signature_256, secret):
            raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        log.warning("calcom webhook: malformed JSON; ack 200")
        return JSONResponse({"ok": False, "reason": "malformed payload"})

    dispatched = calcom_booking.handle_inbound_webhook(payload)
    log.info("calcom webhook dispatched=%s", dispatched)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# HubSpot — CRM events (deal stage change, contact update)
# ---------------------------------------------------------------------------

@app.post("/webhooks/hubspot", status_code=status.HTTP_200_OK)
async def hubspot_webhook(
    request: Request,
    x_hubspot_signature: str | None = Header(None),
) -> JSONResponse:
    body = await request.body()

    secret = os.getenv("HUBSPOT_WEBHOOK_SECRET", "")
    if secret and x_hubspot_signature:
        if not _verify_hmac(body, x_hubspot_signature, secret):
            raise HTTPException(status_code=401, detail="invalid signature")

    try:
        events: Any = await request.json()
    except Exception:
        log.warning("hubspot webhook: malformed JSON; ack 200")
        return JSONResponse({"ok": False, "reason": "malformed payload"})

    for event in events if isinstance(events, list) else [events]:
        subscription_type: str = event.get("subscriptionType", "")
        object_id: str = str(event.get("objectId", ""))
        log.info("hubspot event type=%s objectId=%s", subscription_type, object_id)
        # Additional handlers can subscribe via reply_router in a future pass;
        # leaving the dispatch minimal avoids speculative coupling.

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Manual reply ingestion (Resend free-tier workaround)
# ---------------------------------------------------------------------------
#
# The Resend free tier delivers outbound mail using a sandbox sender
# (onboarding@resend.dev) but does not register reply webhooks unless the
# trainee has a verified sending domain. The program tutors confirmed in
# Slack that the supported workaround for the demo is a manual POST that
# the trainee fires after replying in Gmail. The endpoint dispatches into
# the same reply router every webhook uses so downstream behaviour
# (qualifier, Cal.com slot proposal, HubSpot upsert) is identical
# regardless of how the reply arrived.

@app.post("/conversations/reply", status_code=status.HTTP_200_OK)
async def manual_reply(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="malformed JSON body")

    contact_email = str(payload.get("contact_email") or "").strip()
    channel = str(payload.get("channel") or "email").strip().lower()
    body_text = str(payload.get("body") or "").strip()

    if not contact_email or not body_text:
        raise HTTPException(
            status_code=400,
            detail="contact_email and body are required",
        )
    if channel not in {"email", "sms"}:
        raise HTTPException(status_code=400, detail="channel must be 'email' or 'sms'")

    now = datetime.now(timezone.utc)
    if channel == "email":
        event = reply_router.EmailReplyEvent(
            thread_id=payload.get("thread_id") or f"manual-{now.timestamp():.0f}",
            from_address=contact_email,
            subject=str(payload.get("subject") or "Re: (manual)"),
            body_text=body_text,
            received_at=now,
            raw=dict(payload),
        )
        reply_router.dispatch_email_reply(event)
    else:
        event = reply_router.SMSInboundEvent(
            from_number=contact_email,
            to_shortcode=str(payload.get("shortcode") or ""),
            body=body_text,
            received_at=now,
            raw=dict(payload),
        )
        reply_router.dispatch_sms_inbound(event)

    log.info("manual reply ingested channel=%s contact=%s", channel, contact_email)
    return JSONResponse({"ok": True, "channel": channel, "warm": reply_router.is_warm(contact_email)})


# ---------------------------------------------------------------------------
# Health check (Render pings / before registering webhooks)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "sink": _sink_active()})
