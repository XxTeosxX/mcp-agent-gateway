from jwt import PyJWKClient

from app.config import settings


class JWKSClient:
    def __init__(self) -> None:
        self._client = PyJWKClient(settings.jwks_uri, cache_keys=True, lifespan=settings.OAUTH_JWKS_CACHE_TTL)

    def get_signing_key_from_jwt(self, token: str):
        return self._client.get_signing_key_from_jwt(token)


_jwks_client = JWKSClient()
