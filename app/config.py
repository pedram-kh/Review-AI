import json
import os

import boto3
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = ""
    outscraper_api_key: str = ""
    anthropic_api_key: str = ""
    # Signed into every outreach message (LOGIC.md §7b: real name, real reply address).
    reply_address: str = ""
    # Compared (constant-time) against the X-Admin-Key header on every /api/admin/* request
    # (SPRINT_03.md ticket 3.1). Not a Secrets Manager field, same reasoning as reply_address:
    # it's read straight from the environment in both local and AWS Secrets Manager modes.
    admin_api_key: str = ""
    # CORS is restricted to exactly this origin (the Next.js dashboard on Netlify) — see
    # app/main.py. Defaults to the local dev server so `npm run dev` works out of the box.
    # SPRINT_04.md ticket 4.2 also reuses this as the base URL for magic-link emails
    # (`{app_origin}/auth/verify?token=...`) — it's already "the reviewguide-app deployment's
    # public URL", no separate env var needed for the same thing.
    app_origin: str = "http://localhost:3000"
    # SPRINT_04.md ticket 4.2. Left unset until the Stakeholder's Postmark account + verified
    # mail.reviewguide.eu sending domain exist (see SPRINT_04.md's Stakeholder actions table) —
    # app/services/postmark_client.py checks this and only logs (never calls the real API) while
    # it's empty, so /api/auth/request-link works end-to-end today and starts actually emailing
    # the moment this is set, with zero code changes.
    postmark_token: str = ""
    postmark_from_email: str = "alerts@mail.reviewguide.eu"
    postmark_from_name: str = "ReviewGuide"
    # Signs/verifies the 30-day session JWT issued by POST /api/auth/verify. Shared with
    # reviewguide-app's server environment (never its client bundle) so the app can verify a
    # session cookie locally in middleware without a round trip to the backend per page load —
    # same shared-secret pattern as ADMIN_API_KEY between the two repos.
    auth_jwt_secret: str = ""
    # SPRINT_04.md ticket 4.3, TEST MODE ONLY (Rule 2) — left unset until the Stakeholder's
    # Stripe account exists, same "empty = feature quietly unavailable, not a crash" posture as
    # postmark_token above. app/routers/billing.py's checkout/portal endpoints 503 while empty.
    stripe_secret_key: str = ""
    # Verifies the signature on inbound Stripe webhook events (app/routers/billing.py) — without
    # this, POST /api/billing/webhook rejects everything rather than trusting an unverified body.
    stripe_webhook_secret: str = ""
    # The test-mode Price object for the single "ReviewGuide" plan — 39 zł netto/mies + VAT as
    # of ticket 6.6's price revision (tax_behavior=exclusive; supersedes the original 129 zł/mies
    # placeholder from SPRINT_04.md's Stakeholder actions table).
    stripe_price_id: str = ""
    # SPRINT_05.md ticket 5.2. Compared (constant-time) against the X-Job-Key header on
    # POST /api/jobs/poll-customers — the same "shared-secret header, never reaches a browser"
    # posture as admin_api_key, but this one is presented by EventBridge Scheduler's API
    # destination rather than the Next.js dashboard's server.
    job_api_key: str = ""
    # Ticket 6.4 amendment (Stakeholder + PM, 2026-08-14): where app/jobs/poll_customers.py's
    # ops-health-notification email goes. Not a secret (a plain inbox address), same posture as
    # reply_address and app_origin — a plain App Runner env var, not a Secrets Manager field.
    # Empty means the feature is quietly off, same "unset = unavailable, not a crash" posture as
    # postmark_token/stripe_secret_key above.
    ops_alert_email: str = ""


def _load_settings() -> Settings:
    """In production, secrets come from AWS Secrets Manager (AWS_SECRETS_NAME set).
    Locally, they come from .env."""
    secret_name = os.environ.get("AWS_SECRETS_NAME")
    if not secret_name:
        return Settings()

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response["SecretString"])
    return Settings(
        database_url=secret.get("DATABASE_URL", ""),
        outscraper_api_key=secret.get("OUTSCRAPER_API_KEY", ""),
        anthropic_api_key=secret.get("ANTHROPIC_API_KEY", ""),
    )


settings = _load_settings()

# Outscraper Maps search sub-queries per district (LOGIC.md §8 sweep scope). A single query
# for a whole district hits Google Maps' ~120-listing-per-query cap (confirmed live in ticket
# 1.5's first milestone run — Outscraper's own docs recommend splitting into sub-area queries
# for densely populated areas), so each district maps to a LIST of named-sub-area queries
# instead. discover.py loops all sub-queries and dedupes across them via the existing
# place_id-keyed upsert. Extend this dict to open new districts or add sub-areas — no other
# code changes needed.
DISTRICT_QUERIES: dict[str, list[str]] = {
    "srodmiescie": [
        "restaurants, Nowy Świat, Warszawa, Polska",
        "restaurants, Powiśle, Warszawa, Polska",
        "restaurants, Stare Miasto, Warszawa, Polska",
        "restaurants, Krakowskie Przedmieście, Warszawa, Polska",
        "restaurants, Plac Zbawiciela, Warszawa, Polska",
        "restaurants, Plac Konstytucji, Warszawa, Polska",
        "restaurants, Plac Trzech Krzyży, Warszawa, Polska",
        "restaurants, Hala Koszyki, Koszykowa, Warszawa, Polska",
        "restaurants, Muranów, Warszawa, Polska",
        "restaurants, Ordynacka, Foksal, Warszawa, Polska",
    ],
}
