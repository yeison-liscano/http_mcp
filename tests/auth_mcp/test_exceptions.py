from auth_mcp.exceptions import (
    AuthError,
    DiscoveryError,
    InsufficientScopeError,
    PKCEError,
    RegistrationError,
    TokenValidationError,
)


def test_auth_error() -> None:
    error = AuthError("something went wrong")
    assert str(error) == "something went wrong"
    assert error.message == "something went wrong"


def test_token_validation_error_is_auth_error() -> None:
    error = TokenValidationError("token expired")
    assert isinstance(error, AuthError)
    assert error.message == "token expired"


def test_insufficient_scope_error() -> None:
    error = InsufficientScopeError(
        "Missing required scopes",
        required_scopes=("read", "write"),
    )
    assert isinstance(error, AuthError)
    assert error.required_scopes == ("read", "write")
    assert error.message == "Missing required scopes"


def test_discovery_error_is_auth_error() -> None:
    error = DiscoveryError("could not reach server")
    assert isinstance(error, AuthError)


def test_registration_error_is_auth_error() -> None:
    error = RegistrationError("registration denied")
    assert isinstance(error, AuthError)


def test_pkce_error_is_auth_error() -> None:
    error = PKCEError("challenge mismatch")
    assert isinstance(error, AuthError)
