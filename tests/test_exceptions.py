"""Tests for custom exceptions."""

from kahunas_client.exceptions import (
    AuthenticationError,
    KahunasError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TokenExpiredError,
    ValidationError,
)


class TestExceptions:
    def test_base_error(self) -> None:
        e = KahunasError("test error", code=500)
        assert str(e) == "test error"
        assert e.code == 500

    def test_auth_error(self) -> None:
        e = AuthenticationError("bad creds")
        assert isinstance(e, KahunasError)

    def test_token_expired(self) -> None:
        e = TokenExpiredError("expired")
        assert isinstance(e, AuthenticationError)
        assert isinstance(e, KahunasError)

    def test_not_found(self) -> None:
        e = NotFoundError("resource missing", code=404)
        assert e.code == 404

    def test_validation_error(self) -> None:
        e = ValidationError("invalid input", errors=["field required"], code=422)
        assert e.errors == ["field required"]
        assert e.code == 422

    def test_rate_limit(self) -> None:
        e = RateLimitError("slow down", code=429)
        assert e.code == 429

    def test_server_error(self) -> None:
        e = ServerError("internal", code=500)
        assert isinstance(e, KahunasError)
