import os
import tempfile

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "MCP Agent Gateway"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    REDIS_URL: str = ""
    CLIENT_REGISTRY_TTL: int = 86400

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    OAUTH_ISSUER_URL: str = "http://localhost:8080/realms/mcp-gateway"
    # Realm base used to fetch JWKS. Decoupled from OAUTH_ISSUER_URL so the
    # gateway can validate the public `iss` (e.g. localhost) while fetching keys
    # over the internal network (e.g. keycloak:8080) in docker-compose. Empty =>
    # falls back to OAUTH_ISSUER_URL, which is the correct shape for production.
    OAUTH_JWKS_URL: str = ""
    OAUTH_EXPECTED_AUDIENCE: str = "http://localhost:8000/mcp/"
    OAUTH_JWKS_CACHE_TTL: int = 3600

    @property
    def jwks_uri(self) -> str:
        base = self.OAUTH_JWKS_URL or self.OAUTH_ISSUER_URL
        return f"{base}/protocol/openid-connect/certs"

    GATEWAY_BASE_URL: str = "http://localhost:8000"

    ALLOWED_ORIGINS: list[str] = []

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_TOKEN_ENCRYPTION_KEY: str = ""
    # Shared Drive refresh token, provisioned out-of-band (gcloud). Seeded into
    # token:google:shared at boot. Must be issued to GOOGLE_CLIENT_ID/SECRET.
    GOOGLE_SHARED_REFRESH_TOKEN: str = ""

    GOOGLE_DRIVE_TIMEOUT: float = 10.0
    GOOGLE_DRIVE_MAX_CONNECTIONS: int = 100
    GOOGLE_DRIVE_MAX_KEEPALIVE: int = 20
    GOOGLE_DRIVE_MAX_RETRIES: int = 3

    SLACK_TOKEN_ENCRYPTION_KEY: str = ""

    SLACK_TIMEOUT: float = 8.0
    SLACK_MAX_RETRIES: int = 3
    SLACK_SIGNING_SECRET: str = ""
    # Shared Slack identity, provisioned via a single-workspace app install.
    # Seeded into slack:token:shared at boot. xoxb- = bot, xoxp- = user.
    SLACK_SHARED_BOT_TOKEN: str = ""
    SLACK_SHARED_USER_TOKEN: str = ""

    EXPORT_DIR: str = Field(default_factory=lambda: os.path.join(tempfile.gettempdir(), "mcp-exports"))

    DCR_REGISTRATION_ENDPOINT: str = ""
    DCR_INITIAL_ACCESS_TOKEN: str = ""


settings = Settings()
