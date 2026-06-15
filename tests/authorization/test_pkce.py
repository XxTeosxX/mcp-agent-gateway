import pytest

from app.authorization.pkce import validate_pkce_params


def test_valid_s256_challenge_passes() -> None:
    result = validate_pkce_params("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk", "S256")
    assert result is None


def test_missing_challenge_raises() -> None:
    with pytest.raises(ValueError, match="code_challenge is required"):
        validate_pkce_params(None, "S256")


def test_missing_method_raises() -> None:
    with pytest.raises(ValueError, match="code_challenge_method is required"):
        validate_pkce_params("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk", None)


def test_unsupported_method_raises() -> None:
    with pytest.raises(ValueError, match="only S256 is supported"):
        validate_pkce_params("challenge", "plain")


def test_malformed_base64_challenge_raises() -> None:
    with pytest.raises(ValueError, match="code_challenge must be URL-safe base64"):
        validate_pkce_params("not-url-safe!!!", "S256")


def test_lowercase_s256_method_passes() -> None:
    result = validate_pkce_params("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk", "s256")
    assert result is None


def test_wrong_length_challenge_raises() -> None:
    with pytest.raises(ValueError, match="code_challenge must be URL-safe base64"):
        validate_pkce_params("a" * 42, "S256")
    with pytest.raises(ValueError, match="code_challenge must be URL-safe base64"):
        validate_pkce_params("a" * 44, "S256")
