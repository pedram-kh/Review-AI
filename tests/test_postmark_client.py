"""Tests for app/services/postmark_client.py's get_message_delivery_status (SPRINT_05.md
ticket 5.6's admin customers detail). send_email itself is exercised indirectly everywhere it's
mocked (test_auth.py, test_day_one.py, test_poll_customers.py); this file covers the one
function those don't touch.
"""

from unittest.mock import MagicMock, patch

import httpx

from app.services.postmark_client import get_message_delivery_status


@patch("app.services.postmark_client.settings")
def test_returns_none_when_token_unset(mock_settings) -> None:
    mock_settings.postmark_token = ""
    assert get_message_delivery_status("msg-123") is None


@patch("app.services.postmark_client.httpx.get")
@patch("app.services.postmark_client.settings")
def test_returns_status_field_on_success(mock_settings, mock_get) -> None:
    mock_settings.postmark_token = "test-token"
    mock_response = MagicMock()
    mock_response.json.return_value = {"Status": "Sent", "MessageID": "msg-123"}
    mock_get.return_value = mock_response

    result = get_message_delivery_status("msg-123")

    assert result == "Sent"
    mock_response.raise_for_status.assert_called_once()
    called_url = mock_get.call_args.args[0]
    assert "msg-123" in called_url
    assert mock_get.call_args.kwargs["headers"]["X-Postmark-Server-Token"] == "test-token"


@patch("app.services.postmark_client.httpx.get")
@patch("app.services.postmark_client.settings")
def test_degrades_gracefully_on_http_error(mock_settings, mock_get) -> None:
    mock_settings.postmark_token = "test-token"
    mock_get.side_effect = httpx.HTTPError("boom")

    assert get_message_delivery_status("msg-404") is None


@patch("app.services.postmark_client.httpx.get")
@patch("app.services.postmark_client.settings")
def test_degrades_gracefully_on_non_2xx_status(mock_settings, mock_get) -> None:
    mock_settings.postmark_token = "test-token"
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock(status_code=404)
    )
    mock_get.return_value = mock_response

    assert get_message_delivery_status("msg-missing") is None
