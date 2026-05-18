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

    OAUTH_ISSUER_URL: str = "http://localhost:8080/realms/mcp-gateway"
    OAUTH_EXPECTED_AUDIENCE: str = "http://localhost:8000/mcp/"
    OAUTH_JWKS_CACHE_TTL: int = 3600

    GATEWAY_BASE_URL: str = "http://localhost:8000"

    REDIS_URL: str = "redis://localhost:6379"

    DCR_REGISTRATION_ENDPOINT: str = ""
    DCR_INITIAL_ACCESS_TOKEN: str = ""
    CLIENT_REGISTRY_TTL: int = 86400


settings = Settings()
