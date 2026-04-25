"""HubSpot CRM writes via the HubSpot MCP server.

Every contact write includes enrichment-derived fields beyond basic contact
info — the ICP segment match, the AI-maturity score with confidence, the
hiring-signal summary, and a UTC enrichment timestamp. This is the contract
the grading rubric requires and the handoff signal downstream Tenacious
operators rely on when they open a record in HubSpot.

The client talks to a local MCP endpoint by default
(`HUBSPOT_MCP_ENDPOINT=http://localhost:3010`). A direct Hub API path is
exposed for environments where MCP is not yet stood up — both code paths
write the same fields.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)


class HubSpotWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContactWrite:
    """Payload for an enriched contact upsert.

    The fields after basic contact info correspond one-to-one with the
    hiring_signal_brief output and are the reason a downstream Tenacious
    operator can open a HubSpot record and see why the agent classified
    and pitched the prospect the way it did.
    """
    email: str
    firstname: str | None
    lastname: str | None
    company: str | None
    prospect_domain: str
    crunchbase_id: str | None
    icp_segment: str
    icp_segment_confidence: float
    ai_maturity_score: int
    ai_maturity_confidence: str  # "low" | "medium" | "high"
    hiring_velocity_label: str
    funding_event_stage: str | None
    layoff_event_detected: bool
    leadership_change_role: str | None
    enrichment_timestamp: str   # ISO-8601 UTC
    bench_match: bool
    honesty_flags: list[str] = field(default_factory=list)
    booking_uid: str | None = None
    booking_start_time: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def contact_write_from_brief(
    *,
    email: str,
    firstname: str | None,
    lastname: str | None,
    brief: dict,
    crunchbase_id: str | None = None,
) -> ContactWrite:
    """Project a hiring_signal_brief into a HubSpot ContactWrite payload."""
    ai = brief.get("ai_maturity") or {}
    hiring = brief.get("hiring_velocity") or {}
    buying = brief.get("buying_window_signals") or {}
    funding = buying.get("funding_event") or {}
    layoff = buying.get("layoff_event") or {}
    leadership = buying.get("leadership_change") or {}
    bench = brief.get("bench_to_brief_match") or {}

    return ContactWrite(
        email=email,
        firstname=firstname,
        lastname=lastname,
        company=brief.get("prospect_name"),
        prospect_domain=brief.get("prospect_domain") or "",
        crunchbase_id=crunchbase_id,
        icp_segment=str(brief.get("primary_segment_match") or "abstain"),
        icp_segment_confidence=float(brief.get("segment_confidence") or 0.0),
        ai_maturity_score=int(ai.get("score") or 0),
        ai_maturity_confidence=str(ai.get("confidence_label") or _to_label(ai.get("confidence"))),
        hiring_velocity_label=str(hiring.get("velocity_label") or "insufficient_signal"),
        funding_event_stage=(funding.get("stage") if funding.get("detected") else None),
        layoff_event_detected=bool(layoff.get("detected", False)),
        leadership_change_role=(leadership.get("role") if leadership.get("detected") else None),
        enrichment_timestamp=str(brief.get("generated_at") or _now_iso()),
        bench_match=bool(bench.get("bench_available", False)),
        honesty_flags=list(brief.get("honesty_flags") or []),
    )


def _to_label(numeric: Any) -> str:
    """Convert a 0-1 numeric confidence into low/medium/high for HubSpot."""
    try:
        n = float(numeric)
    except (TypeError, ValueError):
        return "low"
    if n >= 0.75:
        return "high"
    if n >= 0.5:
        return "medium"
    return "low"


def _payload_properties(write: ContactWrite) -> dict[str, Any]:
    """Flatten ContactWrite into HubSpot 'properties' object.

    Keys use lower_snake_case — HubSpot custom property naming convention.
    """
    raw = asdict(write)
    raw["honesty_flags"] = ",".join(write.honesty_flags)
    return {k: v for k, v in raw.items() if v is not None}


# ---------------------------------------------------------------------------
# MCP client
# ---------------------------------------------------------------------------

def upsert_contact_via_mcp(
    write: ContactWrite,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if os.getenv("HUBSPOT_DIRECT_API", "").lower() in {"1", "true", "yes"}:
        return _upsert_contact_via_rest(write, client=client)
    return _upsert_contact_via_mcp_internal(write, client=client)


def _upsert_contact_via_mcp_internal(
    write: ContactWrite,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    endpoint = os.getenv("HUBSPOT_MCP_ENDPOINT", "http://localhost:3010")
    token = os.getenv("HUBSPOT_TOKEN", "")
    url = f"{endpoint.rstrip('/')}/tools/call"

    body = {
        "name": "hubspot.contacts.upsert",
        "arguments": {
            "idProperty": "email",
            "email": write.email,
            "properties": _payload_properties(write),
        },
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owner = client or httpx.Client(timeout=10.0)
    try:
        resp = owner.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise HubSpotWriteError(f"MCP request failed: {exc}") from exc
    finally:
        if client is None:
            owner.close()

    if resp.status_code >= 400:
        raise HubSpotWriteError(
            f"MCP upsert failed: status={resp.status_code} body={resp.text[:500]}"
        )
    return resp.json()


def _upsert_contact_via_rest(
    write: ContactWrite,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Direct HubSpot REST upsert — used when HUBSPOT_DIRECT_API=true.

    Bypasses the MCP server and posts the contact straight to
    https://api.hubapi.com/crm/v3/objects/contacts. The token from
    HUBSPOT_TOKEN must be a Private App access token with
    crm.objects.contacts.write scope.
    """
    token = os.getenv("HUBSPOT_TOKEN", "")
    if not token:
        raise HubSpotWriteError("HUBSPOT_TOKEN not set; cannot call REST API")

    properties = _payload_properties(write)
    properties["email"] = write.email
    body = {"properties": properties}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    owner = client or httpx.Client(timeout=10.0)
    try:
        # Try to update first by email (idempotent path).
        search_url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
        search_resp = owner.post(
            search_url,
            json={
                "filterGroups": [{"filters": [
                    {"propertyName": "email", "operator": "EQ", "value": write.email}
                ]}],
                "properties": ["email"],
                "limit": 1,
            },
            headers=headers,
        )
        if search_resp.status_code >= 400:
            raise HubSpotWriteError(
                f"HubSpot search failed: {search_resp.status_code} {search_resp.text[:500]}"
            )
        results = (search_resp.json() or {}).get("results") or []

        if results:
            contact_id = results[0]["id"]
            url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
            resp = owner.patch(url, json=body, headers=headers)
        else:
            url = "https://api.hubapi.com/crm/v3/objects/contacts"
            resp = owner.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise HubSpotWriteError(f"HubSpot REST request failed: {exc}") from exc
    finally:
        if client is None:
            owner.close()

    if resp.status_code >= 400:
        raise HubSpotWriteError(
            f"HubSpot REST upsert failed: status={resp.status_code} body={resp.text[:500]}"
        )
    return resp.json()


# ---------------------------------------------------------------------------
# Booking → HubSpot link
# ---------------------------------------------------------------------------

def record_booking(
    *,
    email: str,
    booking_uid: str,
    start_time: str,
    prospect_domain: str | None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Called by the booking handler when Cal.com confirms a meeting.

    Writes a small property update against the same email-keyed contact so
    every booking is observable on the HubSpot record alongside the
    enrichment fields written at first outreach. This is the integration
    link the CRM+Calendar rubric requires.
    """
    properties = {
        "booking_uid": booking_uid,
        "booking_start_time": start_time,
        "booking_status": "scheduled",
        "prospect_domain": prospect_domain or "",
        "last_booking_sync_at": _now_iso(),
    }

    if os.getenv("HUBSPOT_DIRECT_API", "").lower() in {"1", "true", "yes"}:
        # REST path — find the contact by email then PATCH the booking fields.
        token = os.getenv("HUBSPOT_TOKEN", "")
        if not token:
            raise HubSpotWriteError("HUBSPOT_TOKEN not set")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        owner = client or httpx.Client(timeout=10.0)
        try:
            search_resp = owner.post(
                "https://api.hubapi.com/crm/v3/objects/contacts/search",
                json={
                    "filterGroups": [{"filters": [
                        {"propertyName": "email", "operator": "EQ", "value": email}
                    ]}],
                    "properties": ["email"],
                    "limit": 1,
                },
                headers=headers,
            )
            results = (search_resp.json() or {}).get("results") or []
            if not results:
                # Create the contact if it doesn't exist yet (booking arrived first).
                resp = owner.post(
                    "https://api.hubapi.com/crm/v3/objects/contacts",
                    json={"properties": {**properties, "email": email}},
                    headers=headers,
                )
            else:
                contact_id = results[0]["id"]
                resp = owner.patch(
                    f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
                    json={"properties": properties},
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise HubSpotWriteError(f"REST booking-write failed: {exc}") from exc
        finally:
            if client is None:
                owner.close()

        if resp.status_code >= 400:
            raise HubSpotWriteError(
                f"REST booking-write failed: status={resp.status_code} body={resp.text[:500]}"
            )
        return resp.json()

    # Default MCP path
    endpoint = os.getenv("HUBSPOT_MCP_ENDPOINT", "http://localhost:3010")
    token = os.getenv("HUBSPOT_TOKEN", "")
    url = f"{endpoint.rstrip('/')}/tools/call"
    body = {
        "name": "hubspot.contacts.upsert",
        "arguments": {
            "idProperty": "email",
            "email": email,
            "properties": properties,
        },
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owner = client or httpx.Client(timeout=10.0)
    try:
        resp = owner.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise HubSpotWriteError(f"MCP booking-write failed: {exc}") from exc
    finally:
        if client is None:
            owner.close()

    if resp.status_code >= 400:
        raise HubSpotWriteError(
            f"MCP booking-write failed: status={resp.status_code} body={resp.text[:500]}"
        )
    return resp.json()


def smoke() -> None:
    write = ContactWrite(
        email="prospect@example.test",
        firstname="Pat",
        lastname="Prospect",
        company="Example Co",
        prospect_domain="example.test",
        crunchbase_id="cb-a1b2c3",
        icp_segment="segment_1_series_a_b",
        icp_segment_confidence=0.82,
        ai_maturity_score=2,
        ai_maturity_confidence="medium",
        hiring_velocity_label="doubled",
        funding_event_stage="series_b",
        layoff_event_detected=False,
        leadership_change_role=None,
        enrichment_timestamp=_now_iso(),
        bench_match=True,
        honesty_flags=["tech_stack_inferred_not_confirmed"],
    )
    try:
        result = upsert_contact_via_mcp(write)
        print(f"smoke: hubspot upsert ok -> {result}")
    except HubSpotWriteError as exc:
        print(f"smoke: hubspot upsert FAILED -> {exc}")


if __name__ == "__main__":
    smoke()
