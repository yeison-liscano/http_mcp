from auth_mcp.types.errors import OAuthErrorResponse, WWWAuthenticateChallenge
from auth_mcp.types.metadata import (
    AuthorizationServerMetadata,
    ProtectedResourceMetadata,
)
from auth_mcp.types.oauth import AuthorizationRequest, TokenRequest, TokenResponse
from auth_mcp.types.registration import (
    ClientRegistrationRequest,
    ClientRegistrationResponse,
)

__all__ = (
    "AuthorizationRequest",
    "AuthorizationServerMetadata",
    "ClientRegistrationRequest",
    "ClientRegistrationResponse",
    "OAuthErrorResponse",
    "ProtectedResourceMetadata",
    "TokenRequest",
    "TokenResponse",
    "WWWAuthenticateChallenge",
)
