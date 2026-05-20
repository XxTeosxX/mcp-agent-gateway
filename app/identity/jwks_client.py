from jwt import PyJWKClient

from app.config import settings


class JWKSClient:
    def __init__(self) -> None:
        jwks_uri = f"{settings.OAUTH_ISSUER_URL}/protocol/openid-connect/certs"
        self._client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=settings.OAUTH_JWKS_CACHE_TTL)

    def get_signing_key_from_jwt(self, token: str):
        return self._client.get_signing_key_from_jwt(token)


_jwks_client = JWKSClient()
