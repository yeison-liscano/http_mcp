from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route

from auth_mcp.resource_server.authentication_backend import OAuthAuthenticationBackend
from auth_mcp.resource_server.metadata_endpoint import ProtectedResourceMetadataEndpoint
from auth_mcp.resource_server.middleware import AuthErrorMiddleware, on_auth_error
from auth_mcp.types.metadata import ProtectedResourceMetadata

if TYPE_CHECKING:
    from auth_mcp.authorization_server.client_store import ClientStore
    from auth_mcp.resource_server.token_validator import TokenValidator
    from auth_mcp.types.metadata import AuthorizationServerMetadata
    from http_mcp.server import MCPServer


@dataclass(frozen=True)
class CORSConfig:
    """CORS configuration for the protected MCP application.

    Only set ``allow_origins`` to specific trusted origins. Using ``["*"]``
    with ``allow_credentials=True`` is insecure and will be rejected by browsers.
    """

    allow_origins: tuple[str, ...] = ()
    allow_methods: tuple[str, ...] = ("GET", "POST")
    allow_headers: tuple[str, ...] = ("Authorization", "Content-Type")
    allow_credentials: bool = True


@dataclass(frozen=True)
class ProtectedMCPAppConfig:
    """Configuration for creating a protected MCP application.

    Authentication is required by default (``require_authentication=True``).
    Set to ``False`` only if you intentionally want unauthenticated users
    to access tools/prompts that have no scope requirements.
    """

    mcp_server: MCPServer
    token_validator: TokenValidator
    resource_uri: str
    authorization_servers: tuple[str, ...]
    scopes_supported: tuple[str, ...] | None = None
    mcp_path: str = "/mcp"
    realm: str | None = None
    require_authentication: bool = True
    cors: CORSConfig | None = None
    authorization_server_metadata: AuthorizationServerMetadata | None = None
    client_store: ClientStore | None = None
    extra_middleware: tuple[Middleware, ...] = field(default_factory=tuple)


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
    - Optional CORS middleware via ``config.cors``
    """
    metadata = ProtectedResourceMetadata(
        resource=config.resource_uri,  # type: ignore[arg-type]
        authorization_servers=config.authorization_servers,  # type: ignore[arg-type]
        scopes_supported=config.scopes_supported,
    )
    metadata_endpoint = ProtectedResourceMetadataEndpoint(metadata)
    resource_metadata_url = f"{config.resource_uri}/.well-known/oauth-protected-resource"

    backend = OAuthAuthenticationBackend(
        token_validator=config.token_validator,
        resource_uri=config.resource_uri,
        require_authentication=config.require_authentication,
    )

    middleware: list[Middleware] = []

    if config.cors is not None:
        from starlette.middleware.cors import CORSMiddleware  # noqa: PLC0415

        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=list(config.cors.allow_origins),
                allow_methods=list(config.cors.allow_methods),
                allow_headers=list(config.cors.allow_headers),
                allow_credentials=config.cors.allow_credentials,
            ),
        )

    middleware.extend([
        Middleware(
            AuthErrorMiddleware,
            resource_metadata_url=resource_metadata_url,
            realm=config.realm,
        ),
        Middleware(
            AuthenticationMiddleware,
            backend=backend,
            on_error=on_auth_error,
        ),
        *config.extra_middleware,
    ])

    routes: list[Route] = [
        Route(
            "/.well-known/oauth-protected-resource",
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
        routes.append(
            Route(
                "/.well-known/oauth-authorization-server",
                as_metadata_endpoint,
            ),
        )

    if config.client_store is not None:
        from auth_mcp.authorization_server.registration_endpoint import (  # noqa: PLC0415
            DynamicClientRegistrationEndpoint,
        )

        registration_endpoint = DynamicClientRegistrationEndpoint(config.client_store)
        routes.append(Route("/register", registration_endpoint))

    app = Starlette(
        routes=routes,
        middleware=middleware,
        **starlette_kwargs,  # type: ignore[arg-type]
    )
    app.mount(config.mcp_path, config.mcp_server.app)
    return app
