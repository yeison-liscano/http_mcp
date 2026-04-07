from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Mount, Route

from auth_mcp.resource_server.authentication_backend import OAuthAuthenticationBackend
from auth_mcp.resource_server.metadata_endpoint import ProtectedResourceMetadataEndpoint
from auth_mcp.resource_server.middleware import AuthErrorMiddleware, on_auth_error

if TYPE_CHECKING:
    from auth_mcp.authorization_server.client_store import ClientStore
    from auth_mcp.resource_server.token_validator import TokenValidator
    from auth_mcp.types.metadata import AuthorizationServerMetadata, ProtectedResourceMetadata
    from http_mcp.server import MCPServer


@dataclass(frozen=True)
class ProtectedMCPAppConfig:
    """Configuration for creating a protected MCP application.

    Authentication is required by default (``require_authentication=True``).
    Set to ``False`` only if you intentionally want unauthenticated users
    to access tools/prompts that have no scope requirements.
    """

    mcp_server: MCPServer
    token_validator: TokenValidator
    resource_endpoint: ProtectedResourceMetadata
    mcp_path: str = "/mcp"
    realm: str | None = None
    require_authentication: bool = True
    authorization_server_metadata: AuthorizationServerMetadata | None = None
    client_store: ClientStore | None = None
    middlewares: tuple[Middleware, ...] = field(default_factory=tuple)


def _get_registration_endpoint_path(
    config: ProtectedMCPAppConfig,
) -> str:
    if (
        config.authorization_server_metadata
        and config.authorization_server_metadata.registration_endpoint is not None
    ):
        return config.authorization_server_metadata.registration_endpoint.path or "/register"
    return "/register"

def create_protected_mcp_app(
    config: ProtectedMCPAppConfig,
    **starlette_kwargs: object,
) -> Starlette:
    """Create a Starlette app with OAuth 2.1-protected MCP server and metadata endpoint.

    Wires together:
    - MCPServer mounted at ``config.mcp_path``
    - OAuthAuthenticationBackend for Bearer token validation
    - AuthErrorMiddleware for WWW-Authenticate headers on 401/403
    - Protected Resource Metadata at /.well-known/oauth-protected-resource
    - Optional custom middleware via ``config.middlewares``
    """
    metadata_endpoint = ProtectedResourceMetadataEndpoint(config.resource_endpoint)
    resource_metadata_url = (
        f"/.well-known/oauth-protected-resource{config.mcp_path}"
    )

    routes: list[Route | Mount] = [
        # ends with / because server app is mounted at /
        Route(
            f"/.well-known/oauth-protected-resource{config.mcp_path}/",
            metadata_endpoint,
        ),
    ]

    if config.authorization_server_metadata is not None:
        from auth_mcp.authorization_server.metadata_endpoint import (  # noqa: PLC0415
            AuthorizationServerMetadataEndpoint,
        )

        as_metadata_endpoint = AuthorizationServerMetadataEndpoint(
            config.authorization_server_metadata,
        )
        _path = config.authorization_server_metadata.issuer.path or ""
        auth_server_path = _path if _path != "/" else ""
        auth_server_metadata_path = f"/.well-known/oauth-authorization-server{auth_server_path}"
        routes.append(
            Route(
                auth_server_metadata_path,
                as_metadata_endpoint,
            ),
        )

    if config.client_store is not None:
        from auth_mcp.authorization_server.registration_endpoint import (  # noqa: PLC0415
            DynamicClientRegistrationEndpoint,
        )

        registration_endpoint = DynamicClientRegistrationEndpoint(config.client_store)
        registration_path = _get_registration_endpoint_path(config)
        routes.append(Route(registration_path, registration_endpoint))


    routes.append(
        Mount(
            config.mcp_path,
            config.mcp_server.app,
            middleware=[
                Middleware(
                    AuthErrorMiddleware,
                    resource_metadata_url=resource_metadata_url,
                    realm=config.realm,
                ),
                Middleware(
                    AuthenticationMiddleware,
                        backend=OAuthAuthenticationBackend(
                        token_validator=config.token_validator,
                        resource_uri=str(config.resource_endpoint.resource),
                        require_authentication=config.require_authentication,
                    ),
                    on_error=on_auth_error,
                ),
                *config.middlewares,
            ],
        ),
    )

    return Starlette(
        routes=routes,
        middleware=list(config.middlewares),
        **starlette_kwargs,  # type: ignore[arg-type]
    )
