from unittest.mock import MagicMock, patch

import pytest

from app.jobs.assemble_outreach import (
    CHANNEL_CONTACT_FORM,
    CHANNEL_EMAIL,
    CHANNEL_FACEBOOK,
    main,
    pick_channel,
    run,
)
from app.templates import OutreachContext


def _candidate(lead_id: int, channel: str = CHANNEL_EMAIL):
    return (
        lead_id,
        OutreachContext(
            name=f"Restauracja {lead_id}",
            rating=2,
            generated_response="Szanowni Państwo, dziękujemy za opinię.",
        ),
        channel,
    )


@pytest.mark.parametrize(
    ("fb_url", "email", "expected"),
    [
        ("fb.com/x", "a@b.pl", CHANNEL_FACEBOOK),
        (None, "a@b.pl", CHANNEL_EMAIL),
        ("fb.com/x", None, CHANNEL_FACEBOOK),
        (None, None, CHANNEL_CONTACT_FORM),
    ],
)
def test_pick_channel_follows_logic_priority(fb_url, email, expected) -> None:
    assert pick_channel(fb_url, email) == expected


@patch("app.jobs.assemble_outreach.TEMPLATE_APPROVED_ON", None)
@patch("app.jobs.assemble_outreach.count_health_flagged", return_value=3)
@patch("app.jobs.assemble_outreach.select_candidates")
@patch("app.jobs.assemble_outreach.SessionLocal")
def test_unapproved_template_blocks_every_write(
    mock_session_local: MagicMock,
    mock_candidates: MagicMock,
    _mock_flagged: MagicMock,
    capsys,
) -> None:
    mock_candidates.return_value = [_candidate(1), _candidate(2, CHANNEL_FACEBOOK)]
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    result = run(on_progress=print)

    assert result["template_approved"] is False
    assert result["wrote"] is False
    assert result["queued"] == 0
    mock_session.commit.assert_not_called()

    out = capsys.readouterr().out
    assert "STOPPED" in out
    assert "not Stakeholder-approved" in out
    # It still shows what would be sent, so the copy can be reviewed.
    assert "Dzień dobry," in out


@patch("app.jobs.assemble_outreach.settings")
@patch("app.jobs.assemble_outreach.TEMPLATE_APPROVED_ON", "2026-08-06")
@patch("app.jobs.assemble_outreach.count_health_flagged", return_value=3)
@patch("app.jobs.assemble_outreach.select_candidates")
@patch("app.jobs.assemble_outreach.SessionLocal")
def test_approved_template_queues_every_candidate(
    mock_session_local: MagicMock,
    mock_candidates: MagicMock,
    _mock_flagged: MagicMock,
    mock_settings: MagicMock,
    capsys,
) -> None:
    mock_settings.reply_address = "pedram@example.com"
    mock_candidates.return_value = [_candidate(1), _candidate(2, CHANNEL_FACEBOOK)]
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    result = run(on_progress=print)

    assert result["wrote"] is True
    assert result["queued"] == 2
    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_called_once()
    assert "Queued: 2" in capsys.readouterr().out


@patch("app.jobs.assemble_outreach.settings")
@patch("app.jobs.assemble_outreach.TEMPLATE_APPROVED_ON", "2026-08-06")
@patch("app.jobs.assemble_outreach.count_health_flagged", return_value=0)
@patch("app.jobs.assemble_outreach.select_candidates")
@patch("app.jobs.assemble_outreach.SessionLocal")
def test_missing_reply_address_blocks_queueing(
    mock_session_local: MagicMock,
    mock_candidates: MagicMock,
    _mock_flagged: MagicMock,
    mock_settings: MagicMock,
    capsys,
) -> None:
    # LOGIC.md §7b requires a real reply address; an unsigned message must not be queued.
    mock_settings.reply_address = ""
    mock_candidates.return_value = [_candidate(1)]
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    result = run(on_progress=print)

    assert result["wrote"] is False
    mock_session.commit.assert_not_called()
    assert "refusing to queue messages without a reply address" in capsys.readouterr().out


@patch("app.jobs.assemble_outreach.count_health_flagged", return_value=2)
@patch("app.jobs.assemble_outreach.select_candidates")
@patch("app.jobs.assemble_outreach.SessionLocal")
def test_preview_writes_nothing_and_reports_the_split(
    mock_session_local: MagicMock,
    mock_candidates: MagicMock,
    _mock_flagged: MagicMock,
    capsys,
) -> None:
    mock_candidates.return_value = [
        _candidate(1, CHANNEL_FACEBOOK),
        _candidate(2, CHANNEL_EMAIL),
        _candidate(3, CHANNEL_CONTACT_FORM),
    ]
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    exit_code = main(["--preview"])

    assert exit_code == 0
    mock_session.commit.assert_not_called()
    out = capsys.readouterr().out
    assert "facebook: 1, email: 1, contact form: 1" in out
    assert "Health-flagged leads excluded (never queued): 2" in out
    assert "preview, nothing written" in out


@patch("app.jobs.assemble_outreach.count_health_flagged", return_value=0)
@patch("app.jobs.assemble_outreach.select_candidates", return_value=[])
@patch("app.jobs.assemble_outreach.SessionLocal")
def test_nothing_to_assemble(
    _mock_session_local: MagicMock,
    _mock_candidates: MagicMock,
    _mock_flagged: MagicMock,
    capsys,
) -> None:
    assert main([]) == 0
    assert "Nothing to assemble." in capsys.readouterr().out
