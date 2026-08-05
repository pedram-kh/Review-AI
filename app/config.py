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
