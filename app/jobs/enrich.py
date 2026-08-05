"""Contact enrichment job (LOGIC.md §4 caps, §6 outreach channels).

Usage:
    python -m app.jobs.enrich --yes    # spend: Outscraper Emails & Contacts, $3 / 1k domains
    python -m app.jobs.enrich          # dry run: estimate only, no API call

Takes leads that already have a response (status 'response_generated') whose place has a
website but no contact details yet, asks Outscraper for emails/social links, and writes the
first valid email and Facebook URL onto the place. A lead advances to 'enriched' once its
place has any reachable channel at all (LOGIC.md §6 priority: Facebook -> email -> phone);
leads with no channel stay put and are reported so they can be handled another way.

Existing non-null email/fb_url are never overwritten — enrichment only fills gaps.
"""

import argparse
import sys
from urllib.parse import urlparse

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Lead, Place
from app.services.cost_guard import CostCapExceeded, enforce_caps, estimate_cost
from app.services.outscraper_client import OutscraperClient

GENERATED_STATUS = "response_generated"
ENRICHED_STATUS = "enriched"

# Same lesson as fetch_reviews (ticket 1.5): the SDK serializes the whole query list into the
# GET URL, and a large batch trips an HTTP 414 at the gateway. Domains are shorter than
# place_ids, so 100 leaves plenty of headroom while still batching.
BATCH_SIZE = 100

# Response shape confirmed by inspecting real Emails & Contacts responses (not guessed):
# {"query": "example.pl", "emails": [{"value": ..., "source": ..., "last_seen": ...}, ...],
#  "phones": [{"value": ...}, ...], "socials": {"facebook": url, "instagram": url, ...}}
# We take the first email and the Facebook social link; LOGIC.md §6 doesn't use the others yet.
EMAILS_KEY = "emails"
SOCIALS_KEY = "socials"
FACEBOOK_KEY = "facebook"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich lead places with email/Facebook contacts (LOGIC.md §6)."
    )
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="Also re-query leads already promoted to 'enriched' that still have no email "
        "or Facebook URL (a lead can reach 'enriched' on phone alone).",
    )
    parser.add_argument("--yes", action="store_true", help="Actually call the API and spend money.")
    return parser.parse_args(argv)


def select_targets(session: Session, recheck: bool = False) -> list[tuple[str, str]]:
    """(place_id, website) for lead places that have a website but are still missing both
    email and Facebook URL. Places already holding both are not worth paying to re-scrape.

    By default only leads at 'response_generated' are in scope (the ticket's rule). --recheck
    widens it to leads already at 'enriched' that still lack a web contact: a lead is promoted
    on any channel including a phone from Maps discovery, so it can be 'enriched' and still
    have no email or Facebook page to reach.
    """
    statuses = [GENERATED_STATUS, ENRICHED_STATUS] if recheck else [GENERATED_STATUS]
    stmt = (
        select(Place.place_id, Place.website)
        .join(Lead, Lead.place_id == Place.place_id)
        .where(
            Lead.status.in_(statuses),
            Place.website.isnot(None),
            Place.website != "",
            or_(Place.email.is_(None), Place.fb_url.is_(None)),
        )
        .order_by(Place.place_id)
    )
    return [(row[0], row[1]) for row in session.execute(stmt)]


def to_domain(website: str) -> str | None:
    """Outscraper wants a bare domain. Google Maps websites arrive as full URLs, sometimes
    without a scheme, sometimes with tracking query strings."""
    if not website:
        return None
    candidate = website.strip()
    if "//" not in candidate:
        candidate = f"http://{candidate}"
    host = (urlparse(candidate).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def extract_contacts(record: dict) -> tuple[str | None, str | None]:
    """(email, facebook_url) from one Outscraper contacts record.

    Entries in `emails` are dicts keyed by "value"; tolerate a bare string too, since the
    field is documented loosely and a shape change shouldn't silently drop every contact.
    """
    email = None
    for entry in record.get(EMAILS_KEY) or []:
        candidate = entry.get("value") if isinstance(entry, dict) else entry
        if candidate:
            email = str(candidate).strip()
            break

    socials = record.get(SOCIALS_KEY) or {}
    facebook = socials.get(FACEBOOK_KEY) if isinstance(socials, dict) else None

    return email, str(facebook).strip() if facebook else None


def apply_contacts(session: Session, place_id: str, email: str | None, fb_url: str | None) -> None:
    """Fills only the columns that are currently empty — a value we already hold (e.g. a
    phone or page found during Maps discovery) is more trustworthy than a scrape, so
    COALESCE keeps it and the scraped value is used only where we have nothing."""
    values = {}
    if email:
        values["email"] = func.coalesce(Place.email, email)
    if fb_url:
        values["fb_url"] = func.coalesce(Place.fb_url, fb_url)
    if not values:
        return

    session.execute(update(Place).where(Place.place_id == place_id).values(**values))


def promote_leads(session: Session) -> tuple[int, int]:
    """Advances every 'response_generated' lead whose place now has at least one channel
    (LOGIC.md §6: Facebook, email or phone). Returns (promoted, still_without_channel)."""
    has_channel = or_(
        Place.fb_url.isnot(None), Place.email.isnot(None), Place.phone.isnot(None)
    )

    promotable = session.execute(
        select(Lead.lead_id)
        .join(Place, Place.place_id == Lead.place_id)
        .where(Lead.status == GENERATED_STATUS, has_channel)
    ).scalars().all()

    if promotable:
        session.execute(
            update(Lead).where(Lead.lead_id.in_(promotable)).values(status=ENRICHED_STATUS)
        )

    remaining = session.execute(
        select(Lead.lead_id)
        .join(Place, Place.place_id == Lead.place_id)
        .where(Lead.status == GENERATED_STATUS)
    ).scalars().all()

    return len(promotable), len(remaining)


def coverage(session: Session) -> dict:
    """Channel coverage across all leads that have reached 'enriched' or are waiting at
    'response_generated' — i.e. everything ticket 2.4 will try to queue."""
    rows = session.execute(
        select(Place.fb_url, Place.email, Place.phone)
        .join(Lead, Lead.place_id == Place.place_id)
        .where(Lead.status.in_([GENERATED_STATUS, ENRICHED_STATUS]))
    ).all()

    total = len(rows)
    stats = {
        "total": total,
        "facebook": sum(1 for fb, _, _ in rows if fb),
        "email": sum(1 for _, em, _ in rows if em),
        "phone": sum(1 for _, _, ph in rows if ph),
        "none": sum(1 for fb, em, ph in rows if not (fb or em or ph)),
    }
    return stats


def _chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _pct(part: int, whole: int) -> str:
    return "n/a" if not whole else f"{part / whole * 100:.0f}%"


def run(yes: bool, recheck: bool = False, on_progress=lambda msg: None) -> dict:
    """Core enrichment logic. Always returns a result dict; check result["capped"] for the
    cap-exceeded case and result["ran"] to tell a dry run apart from a real API call."""
    with SessionLocal() as session:
        targets = select_targets(session, recheck=recheck)

    domains: list[str] = []
    domain_to_places: dict[str, list[str]] = {}
    for place_id, website in targets:
        domain = to_domain(website)
        if not domain:
            continue
        if domain not in domain_to_places:
            domain_to_places[domain] = []
            domains.append(domain)
        domain_to_places[domain].append(place_id)

    result: dict = {
        "places_with_website": len(targets),
        "domains": len(domains),
        "capped": False,
        "cap_error": None,
        "estimated_cost_usd": 0.0,
        "ran": False,
        "emails_found": 0,
        "facebook_found": 0,
        "promoted": 0,
        "without_channel": 0,
        "coverage": {},
        "actual_cost_usd": 0.0,
    }

    on_progress(f"Lead places with a website and a missing contact: {len(targets)}")
    on_progress(f"Unique domains to query: {len(domains)}")

    if not domains:
        on_progress("Nothing to enrich.")
        return result

    try:
        estimate = enforce_caps(n_places=0, n_review_records=0, n_domains=len(domains))
    except CostCapExceeded as exc:
        result["capped"] = True
        result["cap_error"] = str(exc)
        on_progress(f"Cost cap exceeded: {exc}")
        return result

    result["estimated_cost_usd"] = estimate.total_usd
    on_progress(f"Estimated cost: ${estimate.total_usd:.2f}")

    if not yes:
        on_progress("Dry run (no --yes passed) — no API call made, nothing spent.")
        return result

    client = OutscraperClient()
    batches = _chunked(domains, BATCH_SIZE)
    emails_found = 0
    facebook_found = 0

    for i, batch in enumerate(batches, start=1):
        on_progress(f"Batch {i}/{len(batches)}: querying {len(batch)} domains...")
        records = client.emails_and_contacts(batch)

        # Committed per batch, like fetch_reviews: a later failure must not discard spend.
        with SessionLocal() as session:
            for record in records:
                domain = to_domain(str(record.get("query") or record.get("domain") or ""))
                place_ids = domain_to_places.get(domain, [])
                if not place_ids:
                    continue
                email, fb_url = extract_contacts(record)
                if not email and not fb_url:
                    continue
                if email:
                    emails_found += 1
                if fb_url:
                    facebook_found += 1
                for place_id in place_ids:
                    apply_contacts(session, place_id, email, fb_url)
            session.commit()

        on_progress(f"Batch {i}/{len(batches)} done ({len(records)} records)")

    with SessionLocal() as session:
        promoted, without_channel = promote_leads(session)
        session.commit()
        stats = coverage(session)

    actual = estimate_cost(n_places=0, n_review_records=0, n_domains=len(domains))
    result.update(
        ran=True,
        emails_found=emails_found,
        facebook_found=facebook_found,
        promoted=promoted,
        without_channel=without_channel,
        coverage=stats,
        actual_cost_usd=actual.total_usd,
    )

    total = stats["total"]
    on_progress(f"Emails found: {emails_found}")
    on_progress(f"Facebook URLs found: {facebook_found}")
    on_progress(f"Leads promoted to '{ENRICHED_STATUS}': {promoted}")
    on_progress(f"Leads still without any channel: {without_channel}")
    on_progress(
        f"Coverage over {total} leads — facebook {_pct(stats['facebook'], total)}, "
        f"email {_pct(stats['email'], total)}, phone {_pct(stats['phone'], total)}, "
        f"none {_pct(stats['none'], total)}"
    )
    on_progress(f"Actual cost estimate: ${actual.total_usd:.2f}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(yes=args.yes, recheck=args.recheck, on_progress=print)
    return 1 if result["capped"] else 0


if __name__ == "__main__":
    sys.exit(main())
