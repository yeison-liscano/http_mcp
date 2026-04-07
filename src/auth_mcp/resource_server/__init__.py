from auth_mcp.resource_server.authentication_backend import OAuthAuthenticationBackend
from auth_mcp.resource_server.integration import (
    ProtectedMCPAppConfig,
    create_protected_mcp_app,
)
from auth_mcp.resource_server.metadata_endpoint import ProtectedResourceMetadataEndpoint
from auth_mcp.resource_server.middleware import (
    AuthErrorMiddleware,
    build_www_authenticate_header,
    on_auth_error,
)
from auth_mcp.resource_server.token_validator import TokenInfo, TokenValidator

__all__ = (
    "AuthErrorMiddleware",
    "OAuthAuthenticationBackend",
    "ProtectedMCPAppConfig",
    "ProtectedResourceMetadataEndpoint",
    "TokenInfo",
    "TokenValidator",
    "build_www_authenticate_header",
    "create_protected_mcp_app",
    "on_auth_error",
)
