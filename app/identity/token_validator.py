import time
from typing import Any

import httpx
import jwt
from jwt import PyJWKClientError

from app.config import settings
from app.identity.jwks_client import _jwks_client


class TokenValidator:
    def validate(self, token: str) -> dict[str, Any]:
        try:
            signing_key = _jwks_client.get_signing_key_from_jwt(token)
        except (PyJWKClientError, httpx.HTTPError) as exc:
            raise ValueError(f"JWKS fetch failed: {exc}") from exc

        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=settings.OAUTH_ISSUER_URL,
                audience=settings.OAUTH_EXPECTED_AUDIENCE,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ValueError("Token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise ValueError("Invalid audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise ValueError("Invalid issuer") from exc
        except jwt.PyJWTError as exc:
            raise ValueError(f"Token invalid: {exc}") from exc

        nbf = claims.get("nbf")
        if nbf is not None and nbf > time.time():
            raise ValueError("Token not yet valid (nbf)")

        return claims


token_validator = TokenValidator()
