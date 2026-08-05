import json
import os

import boto3
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = ""
    outscraper_api_key: str = ""
    anthropic_api_key: str = ""


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
