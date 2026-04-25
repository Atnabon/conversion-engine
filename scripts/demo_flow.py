"""End-to-end demo orchestrator — runs the single-prospect flow live.

Usage (after .env is configured):

    source .venv/bin/activate
    python scripts/demo_flow.py --to YOUR_GMAIL@gmail.com

Steps:
  1. Loads the test-prospect briefs from data/briefs/cb-a1b2c3/.
  2. Composes a signal-grounded outreach email and sends it via Resend
     (kill-switch routes to YOUR address since it's the program staff sink
     in this configuration). Writes 3 HubSpot activity events.
  3. Prints the manual /conversations/reply curl command you should fire
     from a second terminal AFTER you reply in Gmail.
  4. Optionally — when --book is passed — creates a Cal.com booking and
     writes the booking back to HubSpot.

Run with --dry-run to print the steps without touching live providers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent import composer, reply_router  # noqa: E402
from agent.tools import calcom_booking, hubspot_mcp  # noqa: E402


TEST_PROSPECT_DIR = PROJECT_ROOT / "data" / "briefs" / "cb-a1b2c3"


def _load_brief() -> dict:
    """Load the test prospect's hiring signal brief."""
    path = TEST_PROSPECT_DIR / "hiring_signal_brief.json"
    if not path.exists():
        raise FileNotFoundError(f"test brief missing: {path}")
    return json.loads(path.read_text())


def _normalize_brief_for_composer(brief: dict) -> dict:
    """The committed sample brief uses the older flat schema. Normalize it
    to the shape composer expects so the demo runs against the schema the
    pipeline emits today."""
    signals = brief.get("signals") or {}
    funding = signals.get("funding_event") or {}
    layoff = signals.get("layoffs_120d") or {}
    leadership = signals.get("leadership_change_90d") or {}
    velocity = signals.get("job_post_velocity") or {}
    ai = brief.get("ai_maturity") or {}

    velocity_label = "doubled"
    if velocity.get("delta_ratio", 0) >= 3.0:
        velocity_label = "tripled_or_more"
    elif velocity.get("delta_ratio", 0) >= 2.0:
        velocity_label = "doubled"

    return {
        "prospect_domain": "orrin-labs.example",
        "prospect_name": brief.get("prospect", {}).get("name", "Acme Robotics Inc."),
        "generated_at": brief.get("prospect", {}).get(
            "last_enriched_at", datetime.now(timezone.utc).isoformat()
        ),
        "primary_segment_match": _segment_label(brief.get("icp_classification", {})),
        "segment_confidence": brief.get("icp_classification", {}).get("confidence", 0.7),
        "ai_maturity": {
            "score": ai.get("score", 2),
            "confidence_label": ai.get("confidence", "medium"),
        },
        "hiring_velocity": {"velocity_label": velocity_label},
        "buying_window_signals": {
            "funding_event": {
                "detected": funding.get("present", False),
                "stage": (funding.get("round", "")).lower().replace(" ", "_"),
            },
            "layoff_event": {"detected": layoff.get("present", False)},
            "leadership_change": {
                "detected": leadership.get("present", False),
                "role": (leadership.get("role", "")).lower(),
            },
        },
        "bench_to_brief_match": {"bench_available": brief.get("bench_match", {}).get("match", True)},
        "honesty_flags": [],
    }


def _segment_label(icp: dict) -> str:
    seg = icp.get("segment")
    return {
        1: "segment_1_series_a_b",
        2: "segment_2_mid_market_restructure",
        3: "segment_3_leadership_transition",
        4: "segment_4_specialized_capability",
    }.get(seg, "abstain")


def _outreach_body(brief: dict) -> str:
    name = brief.get("prospect_name", "the team")
    role = (brief["buying_window_signals"]["leadership_change"]).get("role")
    funding_stage = (brief["buying_window_signals"]["funding_event"]).get("stage")
    velocity = brief["hiring_velocity"]["velocity_label"].replace("_", " ")
    lines = [
        f"Hi — quick research note on {name}.",
        "",
        f"Public signals: a new {role.upper()} appointment, fresh {funding_stage.replace('_', ' ').title()} funding, "
        f"and engineering hiring that has {velocity} since the prior snapshot.",
        "",
        "Three of your sector peers have opened named MLOps-platform-engineer roles "
        "in the last 60 days; your public job board does not show one yet. That "
        "is the typical bottleneck for teams in your stage — recruiting capacity, "
        "not budget.",
        "",
        "Worth 15 minutes with one of our delivery leads to talk through it?",
        "",
        "— Atnabon, Research Partner",
        "Tenacious Intelligence Corporation",
    ]
    return "\n".join(lines)


def step_1_send_outreach(args, brief: dict) -> None:
    print("=" * 68)
    print("STEP 1 — Send signal-grounded outreach email via Resend")
    print("=" * 68)
    if args.dry_run:
        print(f"[dry-run] would send to: {args.to}")
        print(f"[dry-run] subject: {args.subject}")
        return

    result = composer.compose_outreach_with_slots(
        contact_email=args.to,
        contact_name=args.name,
        brief=brief,
        body_text=_outreach_body(brief),
        subject=args.subject,
        propose_slots=True,
    )
    print(f"sent: {result.sent}")
    print(f"message_id: {result.message_id}")
    print(f"routed_to: {result.routed_to}")
    print(f"booking_link in body: {result.booking_link}")
    print(f"hubspot_activity_id: {result.hubspot_activity_id}")
    if result.error:
        print(f"ERROR: {result.error}")


def step_2_print_reply_curl(args) -> None:
    base = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")
    print()
    print("=" * 68)
    print("STEP 2 — Reply in Gmail, then run this curl from a SECOND terminal")
    print("=" * 68)
    print()
    print(f"""curl -s -X POST {base}/conversations/reply \\
  -H "Content-Type: application/json" \\
  -d '{{
    "contact_email": "{args.to}",
    "channel": "email",
    "thread_id": "thr-acme-001",
    "subject": "Re: {args.subject}",
    "body": "Tuesday at 10 AM works — what is on the agenda?"
  }}' | python3 -m json.tool
""")
    print(f"After this fires, the prospect is warm and HubSpot logs reply_received.")


def step_3_create_booking(args, brief: dict) -> None:
    print()
    print("=" * 68)
    print("STEP 3 — Cal.com booking + HubSpot write-back")
    print("=" * 68)
    if args.dry_run or not args.book:
        print("[skipped] re-run with --book to create the actual booking")
        return

    event_type_id = int(os.getenv("CALCOM_EVENT_TYPE_ID") or 0)
    if not event_type_id:
        print("CALCOM_EVENT_TYPE_ID not set; skipping live booking call")
        return

    start = datetime.now(timezone.utc) + timedelta(days=2, hours=10)
    request = calcom_booking.BookingRequest(
        event_type_id=event_type_id,
        attendee_email=args.to,
        attendee_name=args.name,
        start_time=start,
        timezone="America/New_York",
    )
    confirmation = calcom_booking.create_booking(request)
    print(f"booking uid: {confirmation.uid}")
    print(f"start: {confirmation.start_time}")
    print(f"url: {confirmation.url}")

    # Fire the booking event into the reply router so the calcom_booking
    # handler writes back to HubSpot the same way Cal.com's webhook would.
    reply_router.dispatch_booking(reply_router.BookingEvent(
        booking_uid=confirmation.uid,
        attendee_email=args.to,
        start_time=start,
        status="created",
        prospect_domain=args.to.split("@")[-1],
    ))
    print("booking dispatched to reply router; HubSpot record_booking fired")


def main() -> None:
    parser = argparse.ArgumentParser(description="Conversion Engine demo orchestrator")
    parser.add_argument("--to", required=True, help="Your Resend signup email")
    parser.add_argument("--name", default="Pat Prospect", help="Attendee display name")
    parser.add_argument("--subject", default="Request: 15 minutes on the engineering plan after the CTO transition")
    parser.add_argument("--book", action="store_true", help="Create the Cal.com booking after sending email")
    parser.add_argument("--dry-run", action="store_true", help="Print steps without touching live providers")
    args = parser.parse_args()

    # Wire the reply router so manual replies log to HubSpot too.
    composer.register()
    calcom_booking.register()

    raw = _load_brief()
    brief = _normalize_brief_for_composer(raw)

    step_1_send_outreach(args, brief)
    step_2_print_reply_curl(args)
    step_3_create_booking(args, brief)


if __name__ == "__main__":
    main()
