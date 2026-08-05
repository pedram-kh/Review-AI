"""Response generation job (LOGIC.md §7 generation rules, §3 status lifecycle, §4 caps).

Usage:
    python -m app.jobs.generate --limit 40 --yes    # tuning batch (default limit 40)
    python -m app.jobs.generate --all --yes         # every remaining new lead
    python -m app.jobs.generate                     # dry run: estimate only, no API call

One Claude call per lead (LOGIC.md §7). Stores the text in `leads.generated_response`, advances
status `new` -> `response_generated`, and never touches `leads.notes`, so health flags survive.
Each lead is committed as it completes, so an API failure partway through keeps earlier work.
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Lead, Place, Review
from app.prompts import PROMPT_VERSION, LeadContext, normalize_review_text
from app.response_checks import check_response
from app.services.claude_client import MAX_TOKENS, ClaudeClient
from app.services.claude_guard import ClaudeCallCapExceeded, cost_for_tokens, enforce_call_cap

DEFAULT_LIMIT = 40
NEW_STATUS = "new"
GENERATED_STATUS = "response_generated"

# SPRINT_02.md ticket 2.2 wants the tuning batch to contain 2-3 health-flagged leads so the
# Stakeholder can review that branch of the prompt too. Plain created_at order would very
# likely yield zero of them (9 flagged out of 213 leads), so the batch reserves this many
# slots for the earliest flagged leads and fills the rest in created_at order.
HEALTH_FLAG_QUOTA = 3

REVIEW_DIR = Path(__file__).resolve().parents[2] / "docs" / "review"


@dataclass(frozen=True)
class GenerationTarget:
    lead_id: int
    context: LeadContext


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate owner responses for leads (LOGIC.md §7)."
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--all", action="store_true", help="Generate for every eligible lead.")
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Also regenerate leads that already have a generated_response.",
    )
    parser.add_argument("--yes", action="store_true", help="Actually call the API and spend money.")
    return parser.parse_args(argv)


def load_candidates(session: Session, regenerate: bool) -> list[GenerationTarget]:
    """All eligible leads in created_at order.

    Normal run: leads still awaiting a response (LOGIC.md §3 status='new', nothing generated yet).
    --regenerate: exactly the leads that already carry a generated_response, i.e. the batch
    currently under review — that's the tuning-loop case, re-running the same leads through a
    new prompt version, so it deliberately ignores status and the health-flag quota.
    """
    stmt = (
        select(
            Lead.lead_id,
            Place.name,
            Place.address,
            Review.rating,
            Review.review_date,
            Review.text,
            Lead.notes,
        )
        .select_from(Lead)
        .join(Place, Place.place_id == Lead.place_id)
        .join(Review, Review.review_id == Lead.review_id)
        .order_by(Lead.created_at)
    )
    if regenerate:
        stmt = stmt.where(Lead.generated_response.isnot(None))
    else:
        stmt = stmt.where(Lead.status == NEW_STATUS, Lead.generated_response.is_(None))

    return [
        GenerationTarget(lead_id=row[0], context=LeadContext(*row[1:]))
        for row in session.execute(stmt)
    ]


def count_already_generated(session: Session) -> int:
    return session.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.status == NEW_STATUS, Lead.generated_response.isnot(None))
    ).scalar_one()


def build_batch(candidates: list[GenerationTarget], limit: int) -> list[GenerationTarget]:
    """Takes `limit` leads in created_at order, but reserves up to HEALTH_FLAG_QUOTA slots for
    health-flagged leads so the tuning batch always exercises that prompt branch."""
    flagged = [t for t in candidates if t.context.is_health_flagged]
    plain = [t for t in candidates if not t.context.is_health_flagged]

    n_flagged = min(HEALTH_FLAG_QUOTA, len(flagged), limit)
    chosen = flagged[:n_flagged] + plain[: limit - n_flagged]
    if len(chosen) < limit:
        chosen += flagged[n_flagged : n_flagged + (limit - len(chosen))]

    position = {t.lead_id: i for i, t in enumerate(candidates)}
    return sorted(chosen, key=lambda t: position[t.lead_id])


def write_review_file(
    records: list[tuple[GenerationTarget, str]], run_date: str, directory: Path = REVIEW_DIR
) -> Path:
    """Writes the Stakeholder review file: one section per lead with everything needed to judge
    the response without opening the DB.

    The prompt version is part of the filename so a re-run under a new prompt version sits
    beside the batch it replaces instead of overwriting it — the tuning loop compares them.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"generation_batch_{run_date}_v{PROMPT_VERSION}.md"

    n_flagged = sum(1 for target, _ in records if target.context.is_health_flagged)
    checks = {target.lead_id: check_response(response) for target, response in records}
    truncated = [lid for lid, c in checks.items() if c.truncated]
    signed = [lid for lid, c in checks.items() if c.has_signature]
    denials = [lid for lid, c in checks.items() if c.has_denial]

    lines = [
        f"# Generation batch — {run_date} — prompt v{PROMPT_VERSION}",
        "",
        f"Prompt: `RESPONSE_PROMPT` v{PROMPT_VERSION} (docs/sprints/SPRINT_02.md "
        f"§Prompt v{PROMPT_VERSION}), model `claude-sonnet-5`, `max_tokens={MAX_TOKENS}`.",
        "",
        f"Responses in this batch: **{len(records)}** (health-flagged: **{n_flagged}**).",
        "",
        "## Automated checks",
        "",
        "| Check | Result | Leads |",
        "|---|---|---|",
        f"| Truncated (no sentence-ending punctuation) | {_verdict(truncated)} | "
        f"{_lead_list(truncated)} |",
        f"| Signature / sign-off (rule 2a) | {_verdict(signed)} | {_lead_list(signed)} |",
        f"| Denial wording — needs human look (rule 5) | {_verdict(denials)} | "
        f"{_lead_list(denials)} |",
        "",
        "> Stakeholder: read every response below against LOGIC.md §7 (must / never lists).",
        "> Health-flagged ones additionally must contain zero admission language.",
        "> The checks above are mechanical only — they cannot judge tone or relevance.",
        "",
        "---",
        "",
    ]

    for i, (target, response) in enumerate(records, start=1):
        lead = target.context
        rating = lead.rating if lead.rating is not None else "?"
        flag = lead.notes if lead.is_health_flagged else "—"
        review_date = lead.review_date.date().isoformat() if lead.review_date else "unknown"
        lead_checks = checks[target.lead_id]
        notices = list(lead_checks.failures) + (["denial?"] if lead_checks.has_denial else [])

        lines += [
            f"## {i}. {lead.name or '(no name)'} — {rating}★",
            "",
            f"- **Lead ID:** {target.lead_id}",
            f"- **Address:** {lead.address or '(none)'}",
            f"- **Review date:** {review_date}",
            f"- **Health flag:** {flag}",
            f"- **Checks:** {'⚠️ ' + ', '.join(notices) if notices else 'clean'}",
            "",
            "**Review:**",
            "",
            _blockquote(normalize_review_text(lead.review_text or "")),
            "",
            "**Generated response:**",
            "",
            _blockquote(response),
            "",
            "---",
            "",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _verdict(offenders: list[int]) -> str:
    return "✅ pass" if not offenders else f"⚠️ {len(offenders)}"


def _lead_list(offenders: list[int]) -> str:
    return "—" if not offenders else ", ".join(str(lid) for lid in offenders)


def _blockquote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines()) or ">"


def run(
    limit: int,
    take_all: bool,
    yes: bool,
    regenerate: bool = False,
    on_progress=lambda msg: None,
) -> dict:
    """Core generation logic. Always returns a result dict; check result["capped"] for the
    cap-exceeded case and result["ran"] to tell a dry run apart from real API calls."""
    with SessionLocal() as session:
        candidates = load_candidates(session, regenerate=regenerate)
        skipped_already_generated = 0 if regenerate else count_already_generated(session)

    if take_all:
        targets = candidates
    elif regenerate:
        # The set is already fixed (it's the batch under review), so no quota rebalancing —
        # just the same leads in the same order.
        targets = candidates[:limit]
    else:
        targets = build_batch(candidates, limit)
    n_flagged = sum(1 for t in targets if t.context.is_health_flagged)

    result: dict = {
        "selected": len(targets),
        "health_flagged": n_flagged,
        "skipped_already_generated": skipped_already_generated,
        "capped": False,
        "cap_error": None,
        "estimated_cost_usd": 0.0,
        "ran": False,
        "generated": 0,
        "failures": 0,
        "truncated": 0,
        "signatures": 0,
        "denials": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "actual_cost_usd": 0.0,
        "review_file": None,
    }

    on_progress(f"Leads selected: {len(targets)} (health-flagged: {n_flagged})")
    on_progress(f"Skipped (already generated): {skipped_already_generated}")

    if not targets:
        on_progress("Nothing to generate.")
        return result

    try:
        estimate = enforce_call_cap(len(targets))
    except ClaudeCallCapExceeded as exc:
        result["capped"] = True
        result["cap_error"] = str(exc)
        on_progress(f"Claude call cap exceeded: {exc}")
        return result

    result["estimated_cost_usd"] = estimate.total_usd
    on_progress(
        f"Estimated cost: ${estimate.total_usd:.2f} "
        f"({estimate.n_calls} calls, ~{estimate.input_tokens} in / {estimate.output_tokens} out)"
    )

    if not yes:
        on_progress("Dry run (no --yes passed) — no API call made, nothing spent.")
        return result

    client = ClaudeClient()
    records: list[tuple[GenerationTarget, str]] = []

    for i, target in enumerate(targets, start=1):
        label = f"[{i}/{len(targets)}] {target.context.name or target.lead_id}"
        try:
            response = client.generate_response(target.context)
        except Exception as exc:
            result["failures"] += 1
            on_progress(f"{label} — FAILED: {exc}")
            continue

        # Committed per lead so a later failure can't discard already-paid-for responses.
        with SessionLocal() as session:
            session.execute(
                update(Lead)
                .where(Lead.lead_id == target.lead_id)
                .values(generated_response=response, status=GENERATED_STATUS)
            )
            session.commit()

        records.append((target, response))
        result["generated"] += 1
        flag_note = " [health-flagged]" if target.context.is_health_flagged else ""
        on_progress(f"{label} — ok ({len(response.split())} words){flag_note}")

    run_date = datetime.now(UTC).date().isoformat()
    review_path = write_review_file(records, run_date)

    batch_checks = [check_response(response) for _, response in records]
    result.update(
        truncated=sum(1 for c in batch_checks if c.truncated),
        signatures=sum(1 for c in batch_checks if c.has_signature),
        denials=sum(1 for c in batch_checks if c.has_denial),
    )
    result.update(
        ran=True,
        input_tokens=client.input_tokens,
        output_tokens=client.output_tokens,
        actual_cost_usd=cost_for_tokens(client.input_tokens, client.output_tokens),
        review_file=str(review_path),
    )

    on_progress(f"Generated: {result['generated']}")
    on_progress(f"Failures: {result['failures']}")
    on_progress(
        f"Checks — truncated: {result['truncated']}, signatures: {result['signatures']}, "
        f"denial wording (needs human look): {result['denials']}"
    )
    on_progress(f"Token usage: {client.input_tokens} in / {client.output_tokens} out")
    on_progress(f"Actual cost: ${result['actual_cost_usd']:.2f}")
    on_progress(f"Review file: {review_path}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(
        limit=args.limit,
        take_all=args.all,
        yes=args.yes,
        regenerate=args.regenerate,
        on_progress=print,
    )
    return 1 if result["capped"] else 0


if __name__ == "__main__":
    sys.exit(main())
