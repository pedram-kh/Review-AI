from unittest.mock import MagicMock, patch

import pytest

from app.jobs.enrich import extract_contacts, main, to_domain
from app.services.cost_guard import (
    MAX_DOMAINS_PER_RUN,
    CostCapExceeded,
    enforce_caps,
    estimate_cost,
)


@pytest.mark.parametrize(
    ("website", "expected"),
    [
        ("https://www.example.pl/menu", "example.pl"),
        ("http://example.pl", "example.pl"),
        ("example.pl", "example.pl"),
        ("https://EXAMPLE.pl/?utm_source=google", "example.pl"),
        ("https://sub.example.pl", "sub.example.pl"),
        ("", None),
    ],
)
def test_to_domain_normalizes_google_maps_websites(website: str, expected: str | None) -> None:
    assert to_domain(website) == expected


def test_extract_contacts_reads_the_real_response_shape() -> None:
    # Shape confirmed against live Emails & Contacts responses.
    record = {
        "query": "example.pl",
        "emails": [
            {"value": "kontakt@example.pl", "source": "https://example.pl/kontakt"},
            {"value": "inne@example.pl", "source": "https://example.pl"},
        ],
        "phones": [{"value": "+48 22 000 00 00"}],
        "socials": {
            "facebook": "https://facebook.com/example",
            "instagram": "https://instagram.com/example",
        },
    }

    assert extract_contacts(record) == ("kontakt@example.pl", "https://facebook.com/example")


def test_extract_contacts_tolerates_bare_string_emails() -> None:
    record = {"emails": ["drugi@example.pl"], "socials": {}}

    assert extract_contacts(record) == ("drugi@example.pl", None)


def test_extract_contacts_ignores_socials_without_facebook() -> None:
    record = {"emails": [], "socials": {"instagram": "https://instagram.com/x"}}

    assert extract_contacts(record) == (None, None)


def test_extract_contacts_returns_none_when_nothing_found() -> None:
    assert extract_contacts({"query": "example.pl", "phones": [{"value": "+48"}]}) == (None, None)


def test_domain_cost_is_three_dollars_per_thousand() -> None:
    assert estimate_cost(n_places=0, n_review_records=0, n_domains=1000).total_usd == 3.0
    assert estimate_cost(n_places=0, n_review_records=0, n_domains=213).total_usd == pytest.approx(
        0.639
    )


def test_domain_cap_aborts_before_any_call() -> None:
    enforce_caps(n_places=0, n_review_records=0, n_domains=MAX_DOMAINS_PER_RUN)

    with pytest.raises(CostCapExceeded, match="domains per run"):
        enforce_caps(n_places=0, n_review_records=0, n_domains=MAX_DOMAINS_PER_RUN + 1)


@patch("app.jobs.enrich.select_targets")
@patch("app.jobs.enrich.SessionLocal")
@patch("app.jobs.enrich.OutscraperClient")
def test_dry_run_makes_no_api_call(
    mock_client_cls: MagicMock,
    _mock_session_local: MagicMock,
    mock_targets: MagicMock,
    capsys,
) -> None:
    mock_targets.return_value = [("p1", "https://a.pl"), ("p2", "https://b.pl")]

    exit_code = main([])

    assert exit_code == 0
    mock_client_cls.assert_not_called()
    out = capsys.readouterr().out
    assert "Unique domains to query: 2" in out
    assert "Dry run" in out


@patch("app.jobs.enrich.select_targets")
@patch("app.jobs.enrich.SessionLocal")
@patch("app.jobs.enrich.OutscraperClient")
def test_duplicate_domains_are_queried_once(
    mock_client_cls: MagicMock,
    _mock_session_local: MagicMock,
    mock_targets: MagicMock,
    capsys,
) -> None:
    # Two places sharing one website must not be billed twice.
    mock_targets.return_value = [
        ("p1", "https://www.shared.pl"),
        ("p2", "http://shared.pl/menu"),
        ("p3", "https://other.pl"),
    ]

    main([])

    assert "Unique domains to query: 2" in capsys.readouterr().out


@patch("app.jobs.enrich.coverage")
@patch("app.jobs.enrich.promote_leads", return_value=(2, 1))
@patch("app.jobs.enrich.apply_contacts")
@patch("app.jobs.enrich.select_targets")
@patch("app.jobs.enrich.SessionLocal")
@patch("app.jobs.enrich.OutscraperClient")
def test_yes_run_writes_contacts_and_promotes_leads(
    mock_client_cls: MagicMock,
    mock_session_local: MagicMock,
    mock_targets: MagicMock,
    mock_apply: MagicMock,
    _mock_promote: MagicMock,
    mock_coverage: MagicMock,
    capsys,
) -> None:
    mock_targets.return_value = [("p1", "https://a.pl"), ("p2", "https://b.pl")]
    mock_client_cls.return_value.emails_and_contacts.return_value = [
        {
            "query": "a.pl",
            "emails": [{"value": "kontakt@a.pl"}],
            "socials": {"facebook": "fb.com/a"},
        },
        {"query": "b.pl", "emails": [], "socials": {}},
    ]
    mock_coverage.return_value = {
        "total": 3,
        "facebook": 1,
        "email": 1,
        "phone": 2,
        "none": 1,
    }
    mock_session_local.return_value.__enter__.return_value = MagicMock()

    exit_code = main(["--yes"])

    assert exit_code == 0
    assert mock_client_cls.return_value.emails_and_contacts.call_args.args[0] == ["a.pl", "b.pl"]
    # Only the domain that actually returned contacts gets written.
    assert mock_apply.call_count == 1
    assert mock_apply.call_args.args[1:] == ("p1", "kontakt@a.pl", "fb.com/a")

    out = capsys.readouterr().out
    assert "Emails found: 1" in out
    assert "Leads promoted to 'enriched': 2" in out
    assert "Leads still without any channel: 1" in out
    assert "facebook 33%" in out
    assert "Actual cost estimate: $0.01" in out


@patch("app.jobs.enrich.select_targets", return_value=[])
@patch("app.jobs.enrich.SessionLocal")
@patch("app.jobs.enrich.OutscraperClient")
def test_nothing_to_enrich_is_not_an_error(
    mock_client_cls: MagicMock,
    _mock_session_local: MagicMock,
    _mock_targets: MagicMock,
    capsys,
) -> None:
    assert main(["--yes"]) == 0
    mock_client_cls.assert_not_called()
    assert "Nothing to enrich." in capsys.readouterr().out
