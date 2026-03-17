class AuthError(Exception):
    """Base exception for auth_mcp."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TokenValidationError(AuthError):
    """Token is invalid, expired, or has wrong audience."""


class InsufficientScopeError(AuthError):
    """Token does not have required scopes."""

    def __init__(self, message: str, required_scopes: tuple[str, ...]) -> None:
        self.required_scopes = required_scopes
        super().__init__(message)


class DiscoveryError(AuthError):
    """Failed to discover authorization server."""


class RegistrationError(AuthError):
    """Dynamic client registration failed."""


class PKCEError(AuthError):
    """PKCE verification failed."""
