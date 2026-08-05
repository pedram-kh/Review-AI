from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.jobs.qualify import (
    _detect_health_keyword,
    _passes_q1_rating,
    _passes_q2_no_owner_reply,
    _passes_q3_recent,
    _passes_q4_length,
    _passes_q5_language,
    main,
    qualify,
)
from app.models import Review

NOW = datetime(2026, 8, 5, tzinfo=UTC)
LONG_TEXT = "This restaurant was truly disappointing and the food quality was very poor overall."


def make_review(**overrides) -> Review:
    defaults = dict(
        review_id="r1",
        place_id="p1",
        rating=2,
        text=LONG_TEXT,
        author="A",
        review_date=NOW - timedelta(days=5),
        has_owner_reply=False,
    )
    defaults.update(overrides)
    return Review(**defaults)


# --- individual rule checks -------------------------------------------------


def test_passes_q1_rating() -> None:
    assert _passes_q1_rating(make_review(rating=1)) is True
    assert _passes_q1_rating(make_review(rating=3)) is True
    assert _passes_q1_rating(make_review(rating=4)) is False
    assert _passes_q1_rating(make_review(rating=None)) is False


def test_passes_q2_no_owner_reply() -> None:
    assert _passes_q2_no_owner_reply(make_review(has_owner_reply=False)) is True
    assert _passes_q2_no_owner_reply(make_review(has_owner_reply=True)) is False
    assert _passes_q2_no_owner_reply(make_review(has_owner_reply=None)) is False


def test_passes_q3_recent() -> None:
    review = make_review(review_date=NOW - timedelta(days=29))
    assert _passes_q3_recent(review, NOW) is True

    stale = make_review(review_date=NOW - timedelta(days=31))
    assert _passes_q3_recent(stale, NOW) is False

    assert _passes_q3_recent(make_review(review_date=None), NOW) is False


def test_passes_q4_length() -> None:
    assert _passes_q4_length(make_review(text="x" * 80)) is True
    assert _passes_q4_length(make_review(text="x" * 79)) is False
    assert _passes_q4_length(make_review(text=None)) is False
    assert _passes_q4_length(make_review(text="")) is False


@patch("app.jobs.qualify.langid.classify")
def test_passes_q5_language(mock_classify: MagicMock) -> None:
    mock_classify.return_value = ("pl", -100.0)
    assert _passes_q5_language(make_review(text="Polski tekst")) is True

    mock_classify.return_value = ("de", -100.0)
    assert _passes_q5_language(make_review(text="Deutscher Text")) is False

    assert _passes_q5_language(make_review(text=None)) is False


def test_detect_health_keyword_case_insensitive_match() -> None:
    assert _detect_health_keyword("There was a COCKROACH in my soup") == "cockroach"
    assert _detect_health_keyword("Znalazłem Karaluch w zupie") == "karaluch"


def test_detect_health_keyword_no_match() -> None:
    assert _detect_health_keyword("The food was just bland and cold") is None


def test_detect_health_keyword_whole_word_avoids_substring_false_positive() -> None:
    # "akurat" contains "rat" as a substring but is an unrelated Polish word ("as it happens").
    assert _detect_health_keyword("To nie jest akurat problem żaden, lokal bardzo uroczy.") is None


def test_detect_health_keyword_whole_word_matches_plural() -> None:
    assert _detect_health_keyword("Widziałem tam szczury biegające po kuchni.") == "szczury"


def test_detect_health_keyword_substring_tier_catches_inflections() -> None:
    # "zatru" (tier 2 substring) must still catch inflected forms like "zatrułam".
    assert _detect_health_keyword("Zatrułam się po tym obiedzie, nie polecam.") == "zatru"


def test_detect_health_keyword_zatru_still_matches_genuine_poisoning_forms() -> None:
    assert _detect_health_keyword("Mielismy zatrucie pokarmowe po tym obiedzie.") == "zatru"
    assert _detect_health_keyword("Zatrułam się po tym obiedzie, nie polecam.") == "zatru"


def test_detect_health_keyword_zatru_excludes_employment_false_positive() -> None:
    # LOGIC.md v1.2: "zatru(?!dni)" excludes the unrelated "zatrudnienie/zatrudnić"
    # (hiring/employment) word family — found live in ticket 1.5's milestone run.
    assert (
        _detect_health_keyword("Może pub powinien pomyśleć o zatrudnieniu więcej osób.") is None
    )
    assert _detect_health_keyword("Powinni zatrudnić więcej kelnerów.") is None


# --- qualify() end-to-end (mocked session) ----------------------------------


def _session_with(already_leaded: list[str], reviews: list[Review]) -> MagicMock:
    session = MagicMock()
    review_result = MagicMock()
    review_result.scalars.return_value.all.return_value = reviews

    insert_results = []
    for _ in reviews:
        insert_result = MagicMock()
        insert_result.rowcount = 1
        insert_results.append(insert_result)

    session.execute.side_effect = [
        [(pid,) for pid in already_leaded],
        review_result,
        *insert_results,
    ]
    return session


@patch("app.jobs.qualify.langid.classify", return_value=("en", -100.0))
def test_qualify_creates_lead_for_qualifying_review(mock_classify: MagicMock) -> None:
    review = make_review()
    session = _session_with(already_leaded=[], reviews=[review])

    counters = qualify(session)

    assert counters["scanned"] == 1
    assert counters["created"] == 1
    assert counters["health_flagged"] == 0
    assert all(counters[f"skipped_q{i}"] == 0 for i in range(1, 7))


@patch("app.jobs.qualify.langid.classify", return_value=("en", -100.0))
def test_qualify_skips_place_with_existing_lead(mock_classify: MagicMock) -> None:
    review = make_review()
    session = _session_with(already_leaded=["p1"], reviews=[review])

    counters = qualify(session)

    assert counters["scanned"] == 1
    assert counters["created"] == 0
    assert counters["skipped_q6"] == 1


@patch("app.jobs.qualify.langid.classify", return_value=("en", -100.0))
def test_qualify_skips_by_each_failing_rule(mock_classify: MagicMock) -> None:
    reviews = [
        make_review(review_id="r_q1", rating=5),
        make_review(review_id="r_q2", has_owner_reply=True),
        make_review(review_id="r_q3", review_date=NOW - timedelta(days=60)),
        make_review(review_id="r_q4", text="short"),
    ]
    session = _session_with(already_leaded=[], reviews=reviews)

    counters = qualify(session)

    assert counters["scanned"] == 4
    assert counters["created"] == 0
    assert counters["skipped_q1"] == 1
    assert counters["skipped_q2"] == 1
    assert counters["skipped_q3"] == 1
    assert counters["skipped_q4"] == 1


@patch("app.jobs.qualify.langid.classify", return_value=("de", -100.0))
def test_qualify_skips_q5_for_disallowed_language(mock_classify: MagicMock) -> None:
    review = make_review()
    session = _session_with(already_leaded=[], reviews=[review])

    counters = qualify(session)

    assert counters["created"] == 0
    assert counters["skipped_q5"] == 1


@patch("app.jobs.qualify.langid.classify", return_value=("en", -100.0))
def test_qualify_picks_most_recent_qualifying_review_per_place(mock_classify: MagicMock) -> None:
    older = make_review(review_id="r_old", review_date=NOW - timedelta(days=10))
    newer = make_review(review_id="r_new", review_date=NOW - timedelta(days=1))
    session = _session_with(already_leaded=[], reviews=[older, newer])

    counters = qualify(session)

    assert counters["created"] == 1
    assert counters["skipped_q6"] == 1  # the older, superseded candidate

    insert_call = session.execute.call_args_list[-1]
    compiled_values = insert_call[0][0].compile().params
    assert compiled_values["review_id"] == "r_new"


@patch("app.jobs.qualify.langid.classify", return_value=("en", -100.0))
def test_qualify_flags_health_keyword_in_notes(mock_classify: MagicMock) -> None:
    review = make_review(text=LONG_TEXT + " There was a cockroach in the kitchen area too.")
    session = _session_with(already_leaded=[], reviews=[review])

    counters = qualify(session)

    assert counters["created"] == 1
    assert counters["health_flagged"] == 1

    insert_call = session.execute.call_args_list[-1]
    compiled_values = insert_call[0][0].compile().params
    assert compiled_values["notes"] == "HEALTH_FLAG: cockroach"


@patch("app.jobs.qualify.SessionLocal")
def test_main_prints_all_counters(mock_session_local: MagicMock, capsys) -> None:
    session = _session_with(already_leaded=[], reviews=[])
    mock_session_local.return_value.__enter__.return_value = session

    exit_code = main([])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Reviews scanned: 0" in out
    assert "Leads created: 0" in out
    assert "Health-flagged: 0" in out
    for q in ("q1", "q2", "q3", "q4", "q5", "q6"):
        assert f"{q}: 0" in out
