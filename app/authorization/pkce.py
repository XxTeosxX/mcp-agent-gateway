import base64
import binascii
import re


def validate_pkce_params(code_challenge: str | None, code_challenge_method: str | None) -> None:
    """Validate OAuth 2.1 PKCE parameters for authorization requests.

    OAuth 2.1 requires PKCE for all public and confidential clients using
    the authorization code flow. This helper enforces the gateway's policy
    before redirecting to the upstream identity provider.
    """
    if not code_challenge:
        raise ValueError("code_challenge is required")
    if not code_challenge_method:
        raise ValueError("code_challenge_method is required")
    if code_challenge_method.upper() != "S256":
        raise ValueError("only S256 is supported")

    # code_challenge must be the base64url encoding of a SHA-256 digest (43 chars for 32 bytes)
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code_challenge):
        raise ValueError("code_challenge must be URL-safe base64")

    # Verify it is decodable base64url (catches padding / charset mistakes)
    try:
        base64.urlsafe_b64decode(code_challenge + "=")
    except (binascii.Error, ValueError) as exc:
        raise ValueError("code_challenge must be URL-safe base64") from exc
