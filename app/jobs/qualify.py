"""Lead qualification job (LOGIC.md §1 Q1-Q6, §2 health flag, §3 status lifecycle).

Usage:
    python -m app.jobs.qualify

Pure DB scan + local language detection — no API calls, no cost, no --yes needed.
"""

import re
import sys
from datetime import UTC, datetime, timedelta

import py3langid as langid
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.logic_rules import (
    ALLOWED_LANGUAGES,
    HEALTH_KEYWORDS_SUBSTRING,
    HEALTH_KEYWORDS_WHOLE_WORD,
    MAX_RATING_FOR_LEAD,
    MAX_REVIEW_AGE_DAYS,
    MIN_TEXT_LENGTH,
)
from app.models import Lead, Review

RULE_KEYS = ("q1", "q2", "q3", "q4", "q5", "q6")

_WHOLE_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in HEALTH_KEYWORDS_WHOLE_WORD) + r")\b",
    re.IGNORECASE,
)


def _passes_q1_rating(review: Review) -> bool:
    return review.rating is not None and review.rating <= MAX_RATING_FOR_LEAD


def _passes_q2_no_owner_reply(review: Review) -> bool:
    # Literal false required — NULL (unknown) does not count as "no reply".
    return review.has_owner_reply is False


def _passes_q3_recent(review: Review, now: datetime) -> bool:
    if review.review_date is None:
        return False
    return (now - review.review_date) <= timedelta(days=MAX_REVIEW_AGE_DAYS)


def _passes_q4_length(review: Review) -> bool:
    return bool(review.text) and len(review.text) >= MIN_TEXT_LENGTH


def _passes_q5_language(review: Review) -> bool:
    if not review.text:
        return False
    lang, _score = langid.classify(review.text)
    return lang in ALLOWED_LANGUAGES


def _detect_health_keyword(text: str) -> str | None:
    whole_word_match = _WHOLE_WORD_PATTERN.search(text)
    if whole_word_match:
        return whole_word_match.group(1).lower()

    for label, pattern in HEALTH_KEYWORDS_SUBSTRING:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return None


def qualify(session: Session) -> dict[str, int]:
    counters = {"scanned": 0, "created": 0, "health_flagged": 0}
    counters.update({f"skipped_{q}": 0 for q in RULE_KEYS})

    already_leaded_place_ids = {row[0] for row in session.execute(select(Lead.place_id))}
    reviews = session.execute(select(Review)).scalars().all()
    now = datetime.now(UTC)

    candidates_by_place: dict[str, Review] = {}

    for review in reviews:
        counters["scanned"] += 1

        if review.place_id in already_leaded_place_ids:
            counters["skipped_q6"] += 1
            continue
        if not _passes_q1_rating(review):
            counters["skipped_q1"] += 1
            continue
        if not _passes_q2_no_owner_reply(review):
            counters["skipped_q2"] += 1
            continue
        if not _passes_q3_recent(review, now):
            counters["skipped_q3"] += 1
            continue
        if not _passes_q4_length(review):
            counters["skipped_q4"] += 1
            continue
        if not _passes_q5_language(review):
            counters["skipped_q5"] += 1
            continue

        # Passed Q1-Q5. LOGIC.md §1: "If a place has multiple qualifying reviews, pick the
        # most recent one" — the one-lead-per-place dedupe intent is the same as Q6, so any
        # review here that loses to a more recent one for the same place is tallied as q6.
        current_best = candidates_by_place.get(review.place_id)
        if current_best is None:
            candidates_by_place[review.place_id] = review
        elif review.review_date is not None and (
            current_best.review_date is None or review.review_date > current_best.review_date
        ):
            candidates_by_place[review.place_id] = review
            counters["skipped_q6"] += 1
        else:
            counters["skipped_q6"] += 1

    for place_id, review in candidates_by_place.items():
        keyword = _detect_health_keyword(review.text or "")
        notes = f"HEALTH_FLAG: {keyword}" if keyword else None
        if keyword:
            counters["health_flagged"] += 1

        stmt = (
            pg_insert(Lead)
            .values(place_id=place_id, review_id=review.review_id, status="new", notes=notes)
            .on_conflict_do_nothing(index_elements=[Lead.place_id])
        )
        result = session.execute(stmt)
        if result.rowcount:
            counters["created"] += 1
        else:
            # Race-safety net: place picked up a lead between our pre-check and this insert.
            counters["skipped_q6"] += 1
            if keyword:
                counters["health_flagged"] -= 1

    return counters


def main(argv: list[str] | None = None) -> int:
    with SessionLocal() as session:
        counters = qualify(session)
        session.commit()

    print(f"Reviews scanned: {counters['scanned']}")
    print(f"Leads created: {counters['created']}")
    print(f"Health-flagged: {counters['health_flagged']}")
    print("Skipped by rule:")
    for q in RULE_KEYS:
        print(f"  {q}: {counters[f'skipped_{q}']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
