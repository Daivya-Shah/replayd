from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    UPSTREAM_BASE_URL: str = "https://api.openai.com"
    LISTEN_HOST: str = "127.0.0.1"
    LISTEN_PORT: int = 8787
    MGMT_HOST: str = "127.0.0.1"
    MGMT_PORT: int = 8788
    MGMT_CORS_ORIGIN: str = "http://localhost:3000"
    STORAGE_DIR: str = "./data"
    CAPTURE_ENABLED: bool = True
    RUN_ID_HEADER: str = "x-replayd-run-id"
    REPLAY_HEADER: str = "x-replayd-replay"
    BRANCH_HEADER: str = "x-replayd-branch"
    INGEST_KEY_HEADER: str = "x-replayd-key"
    REQUIRE_INGEST_KEY: bool = False
    REPLAYD_API_TOKEN: str | None = None
    OIDC_ISSUER: str | None = None
    OIDC_AUDIENCE: str | None = None
    OIDC_JWKS_URL: str | None = None
    OIDC_ALGORITHMS: str = "ES384,RS256"
    DATABASE_URL: str | None = None
    RUN_MIGRATIONS_ON_STARTUP: bool = True
    BLOB_STORAGE_BACKEND: Literal["filesystem", "s3"] = "filesystem"
    BLOB_S3_ENDPOINT_URL: str | None = None
    BLOB_S3_BUCKET: str = "replayd"
    BLOB_S3_REGION: str = "us-east-1"
    BLOB_S3_ACCESS_KEY_ID: str | None = None
    BLOB_S3_SECRET_ACCESS_KEY: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
