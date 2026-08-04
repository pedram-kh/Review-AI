"""Verifies Outscraper and Anthropic API keys are working. Prints both results, nothing stored.

COST GUARD: the Anthropic call is a single request with max_tokens=10. No loops.

Usage: python scripts/check_apis.py
"""

import sys

import httpx
from anthropic import Anthropic

from app.config import settings

OUTSCRAPER_BALANCE_URL = "https://api.outscraper.com/profile/balance"


def check_outscraper() -> bool:
    try:
        response = httpx.get(
            OUTSCRAPER_BALANCE_URL,
            headers={"X-API-KEY": settings.outscraper_api_key},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        status, balance = data.get("account_status"), data.get("balance")
        print(f"outscraper: ok (status={status}, balance={balance})")
        return True
    except Exception as exc:
        print(f"outscraper: error ({exc})")
        return False


def check_anthropic() -> bool:
    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        reply = "".join(block.text for block in message.content if block.type == "text")
        print(f"anthropic: ok (reply={reply!r})")
        return True
    except Exception as exc:
        print(f"anthropic: error ({exc})")
        return False


def main() -> int:
    outscraper_ok = check_outscraper()
    anthropic_ok = check_anthropic()
    return 0 if outscraper_ok and anthropic_ok else 1


if __name__ == "__main__":
    sys.exit(main())
