from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthorizationCodeTokenRequest(BaseModel):
    """OAuth 2.1 token request exchanging an authorization code, verified with PKCE."""

    model_config = ConfigDict(frozen=True)

    grant_type: Literal["authorization_code"]
    code: str
    code_verifier: str
    redirect_uri: str | None = None
    client_id: str | None = None
    resource: str | None = None


class RefreshTokenRequest(BaseModel):
    """OAuth 2.1 token request exchanging a refresh token."""

    model_config = ConfigDict(frozen=True)

    grant_type: Literal["refresh_token"]
    refresh_token: str
    client_id: str | None = None
    resource: str | None = None


TokenRequest = Annotated[
    AuthorizationCodeTokenRequest | RefreshTokenRequest,
    Field(discriminator="grant_type"),
]


class TokenResponse(BaseModel):
    """OAuth 2.1 token response."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: str = "Bearer"  # noqa: S105
    expires_in: int
    refresh_token: str | None = None
    scope: str | None = None


class AuthorizationRequest(BaseModel):
    """OAuth 2.1 authorization request with PKCE."""

    model_config = ConfigDict(frozen=True)

    response_type: Literal["code"] = "code"
    client_id: str
    redirect_uri: str
    scope: str | None = None
    state: str | None = None
    code_challenge: str
    code_challenge_method: Literal["S256"] = "S256"
    resource: str | None = None
