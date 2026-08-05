"""Outreach assembly job (LOGIC.md §6 channels, §7b message rules).

Usage:
    python -m app.jobs.assemble_outreach            # preview / assemble
    python -m app.jobs.assemble_outreach --preview  # never writes, just shows one sample

No API calls, nothing to spend. Fills `leads.outreach_message` for enriched, non-health-flagged
leads, picks the channel by LOGIC.md §6 priority (Facebook -> email -> contact form) and moves
the lead to 'queued'.

Health-flagged leads are never queued (LOGIC.md §2/§6, standing constraint #3) — they are
counted and skipped so the Stakeholder can handle them by hand.

While app/templates.py has TEMPLATE_APPROVED_ON = None the job refuses to write anything: the
Stakeholder must approve the copy before any lead carries it (SPRINT_02.md ticket 2.4).
"""

import argparse
import sys

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Lead, Place, Review
from app.prompts import HEALTH_FLAG_MARKER
from app.templates import TEMPLATE_APPROVED_ON, OutreachContext, render_outreach

ENRICHED_STATUS = "enriched"
QUEUED_STATUS = "queued"

CHANNEL_FACEBOOK = "facebook"
CHANNEL_EMAIL = "email"
CHANNEL_CONTACT_FORM = "contact_form"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble outreach messages for enriched leads (LOGIC.md §6, §7b)."
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Render and show one sample message without writing anything.",
    )
    return parser.parse_args(argv)


def pick_channel(fb_url: str | None, email: str | None) -> str:
    """LOGIC.md §6 channel priority. Contact form is the fallback when we hold neither a
    Facebook page nor an email — a human works those from the website."""
    if fb_url:
        return CHANNEL_FACEBOOK
    if email:
        return CHANNEL_EMAIL
    return CHANNEL_CONTACT_FORM


def select_candidates(session: Session) -> list[tuple[int, OutreachContext, str]]:
    """(lead_id, context, channel) for every enriched lead that may be queued.

    Health-flagged leads are excluded in SQL rather than filtered afterwards, so there is no
    code path in which one reaches the assembly step at all.
    """
    stmt = (
        select(
            Lead.lead_id,
            Place.name,
            Review.rating,
            Lead.generated_response,
            Place.fb_url,
            Place.email,
        )
        .select_from(Lead)
        .join(Place, Place.place_id == Lead.place_id)
        .join(Review, Review.review_id == Lead.review_id)
        .where(
            Lead.status == ENRICHED_STATUS,
            Lead.generated_response.isnot(None),
            or_not_health_flagged(),
        )
        .order_by(Lead.created_at)
    )

    return [
        (
            row[0],
            OutreachContext(name=row[1], rating=row[2], generated_response=row[3]),
            pick_channel(row[4], row[5]),
        )
        for row in session.execute(stmt)
    ]


def or_not_health_flagged():
    """`notes NOT LIKE '%HEALTH_FLAG%'` that also keeps rows where notes IS NULL — in SQL a
    NULL comparison is NULL, not true, so a plain NOT LIKE would silently drop unflagged
    leads whose notes were never set."""
    return Lead.notes.is_(None) | ~Lead.notes.contains(HEALTH_FLAG_MARKER)


def count_health_flagged(session: Session) -> int:
    return len(
        session.execute(
            select(Lead.lead_id).where(
                Lead.status == ENRICHED_STATUS,
                Lead.notes.contains(HEALTH_FLAG_MARKER),
            )
        )
        .scalars()
        .all()
    )


def run(preview: bool = False, on_progress=lambda msg: None) -> dict:
    """Core assembly logic. Returns a result dict; result["wrote"] distinguishes a real run
    from a preview or an approval-blocked run."""
    with SessionLocal() as session:
        candidates = select_candidates(session)
        health_flagged = count_health_flagged(session)

    by_channel = {CHANNEL_FACEBOOK: 0, CHANNEL_EMAIL: 0, CHANNEL_CONTACT_FORM: 0}
    for _, _, channel in candidates:
        by_channel[channel] += 1

    result: dict = {
        "candidates": len(candidates),
        "health_flagged_excluded": health_flagged,
        "by_channel": by_channel,
        "template_approved": TEMPLATE_APPROVED_ON is not None,
        "wrote": False,
        "queued": 0,
    }

    on_progress(f"Enriched leads eligible for outreach: {len(candidates)}")
    on_progress(f"Health-flagged leads excluded (never queued): {health_flagged}")
    on_progress(
        f"Channel split — facebook: {by_channel[CHANNEL_FACEBOOK]}, "
        f"email: {by_channel[CHANNEL_EMAIL]}, "
        f"contact form: {by_channel[CHANNEL_CONTACT_FORM]}"
    )

    if not candidates:
        on_progress("Nothing to assemble.")
        return result

    reply_address = settings.reply_address
    if not reply_address:
        on_progress("WARNING: REPLY_ADDRESS is not configured — messages would be unsigned.")

    sample = render_outreach(candidates[0][1], reply_address)

    if preview:
        on_progress("\n--- sample message (preview, nothing written) ---\n")
        on_progress(sample)
        return result

    if TEMPLATE_APPROVED_ON is None:
        on_progress(
            "\nSTOPPED: the outreach template is not Stakeholder-approved yet "
            "(app/templates.py TEMPLATE_APPROVED_ON is None), so no lead was queued. "
            "Set the approval date there once PROGRESS.md records the sign-off."
        )
        on_progress("\n--- sample of what would be sent ---\n")
        on_progress(sample)
        return result

    if not reply_address:
        on_progress("STOPPED: refusing to queue messages without a reply address (LOGIC.md §7b).")
        return result

    with SessionLocal() as session:
        for lead_id, context, channel in candidates:
            session.execute(
                update(Lead)
                .where(Lead.lead_id == lead_id)
                .values(
                    outreach_message=render_outreach(context, reply_address),
                    channel=channel,
                    status=QUEUED_STATUS,
                )
            )
        session.commit()

    result.update(wrote=True, queued=len(candidates))
    on_progress(f"Queued: {len(candidates)}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run(preview=args.preview, on_progress=print)
    return 0


if __name__ == "__main__":
    sys.exit(main())
