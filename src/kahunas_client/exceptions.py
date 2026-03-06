"""Custom exceptions for the Kahunas client."""


class KahunasError(Exception):
    """Base exception for all Kahunas client errors."""

    def __init__(self, message: str, code: int | None = None) -> None:
        self.code = code
        super().__init__(message)


class AuthenticationError(KahunasError):
    """Raised when authentication fails or token is invalid."""


class TokenExpiredError(AuthenticationError):
    """Raised when the auth token has expired and needs refresh."""


class NotFoundError(KahunasError):
    """Raised when a requested resource is not found (404)."""


class ValidationError(KahunasError):
    """Raised when the API returns a validation error (422)."""

    def __init__(
        self, message: str, errors: list[str] | None = None, code: int | None = None
    ) -> None:
        self.errors = errors or []
        super().__init__(message, code)


class RateLimitError(KahunasError):
    """Raised when rate limited by the API (429)."""


class ServerError(KahunasError):
    """Raised when the API returns a server error (5xx)."""
