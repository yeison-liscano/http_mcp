# auth_mcp

OAuth 2.1 authorization for MCP servers, built on top of `http_mcp` and
Starlette. Implements the MCP Authorization specification with Protected
Resource Metadata (RFC 9728), Bearer token validation, and proper
`WWW-Authenticate` error responses.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
  - [Middleware Stack](#middleware-stack)
  - [Request Authentication Flow](#request-authentication-flow)
- [Components](#components)
  - [Token Validator](#token-validator)
  - [Authentication Backend](#authentication-backend)
  - [Protected Resource Metadata](#protected-resource-metadata)
  - [WWW-Authenticate Middleware](#www-authenticate-middleware)
  - [Integration Helper](#integration-helper)
- [Best Practices](#best-practices)
  - [Token Validation](#token-validation)
  - [Scope Design](#scope-design)
  - [Deployment](#deployment)
- [Use Cases](#use-cases)
  - [MCP Server with External OAuth Provider](#mcp-server-with-external-oauth-provider)
  - [Mixed Public and Private Tools](#mixed-public-and-private-tools)
  - [Browser-Based MCP Client with CORS](#browser-based-mcp-client-with-cors)
- [Security Surfaces by Endpoint](#security-surfaces-by-endpoint)

## Installation

`auth_mcp` is included with `http-mcp`:

```bash
pip install http-mcp
```

## Quick Start

```python
from http_mcp.server import MCPServer
from auth_mcp.resource_server import (
    ProtectedMCPAppConfig,
    TokenInfo,
    TokenValidator,
    create_protected_mcp_app,
)


class MyTokenValidator(TokenValidator):
    async def validate_token(
        self, token: str, resource: str | None = None
    ) -> TokenInfo | None:
        # Validate token against your authorization server
        # Use hmac.compare_digest() for constant-time comparison
        ...


mcp_server = MCPServer(name="my-server", version="1.0.0", tools=MY_TOOLS)

config = ProtectedMCPAppConfig(
    mcp_server=mcp_server,
    token_validator=MyTokenValidator(),
    resource_uri="https://mcp.example.com",
    authorization_servers=("https://auth.example.com",),
    scopes_supported=("read", "write"),
)

app = create_protected_mcp_app(config)
```

This gives you:

- Bearer token validation on all MCP endpoints
- `/.well-known/oauth-protected-resource` metadata endpoint
- `WWW-Authenticate` headers on 401/403 responses with `resource_metadata`
  discovery parameter
- `Strict-Transport-Security`, `X-Content-Type-Options`, and `Cache-Control`
  security headers

## Architecture Overview

`auth_mcp` wraps your `MCPServer` in a layered Starlette application assembled
by `create_protected_mcp_app()`. Understanding the layers makes it easier to
reason about what happens on every request.

### Middleware Stack

```
Incoming HTTP request
        │
        ▼
┌─────────────────────────┐
│     CORSMiddleware      │  (optional — only when config.cors is set)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│   AuthErrorMiddleware   │  Adds HSTS / nosniff / no-store to all responses.
│                         │  On 401/403: injects WWW-Authenticate header with
│                         │  resource_metadata discovery URL.
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ AuthenticationMiddleware│  Starlette built-in. Calls
│  (OAuth Backend)        │  OAuthAuthenticationBackend.authenticate() on every
│                         │  request and populates request.user / request.auth.
└───────────┬─────────────┘
            │
       ┌────┴──────────────────────────────┐
       │                                   │
       ▼                                   ▼
┌─────────────────┐             ┌──────────────────────────────┐
│   MCPServer     │             │ ProtectedResourceMetadata    │
│ (at mcp_path,   │             │ Endpoint                     │
│  default /mcp)  │             │ /.well-known/oauth-protected-│
│                 │             │ resource                     │
└─────────────────┘             └──────────────────────────────┘
```

### Request Authentication Flow

The following steps describe what happens when a client sends `POST /mcp`:

1. **`AuthenticationMiddleware`** calls
   `OAuthAuthenticationBackend.authenticate()`:

   - If the `Authorization` header is missing and `require_authentication=True`,
     raises `AuthenticationError` → 401.
   - If the scheme is not `Bearer`, raises `AuthenticationError` → 401.
   - If the token exceeds 2048 characters or contains characters outside the RFC
     6750 `b64token` alphabet, the token is rejected without calling the
     validator → 401.
   - Calls `TokenValidator.validate_token(token, resource_uri)`. A `None` return
     means the token is invalid or expired → 401.
   - On success, sets `request.user` (`SimpleUser(subject)`) and `request.auth`
     (`AuthCredentials(scopes)`) for downstream handlers.

1. **`MCPServer`** handles the JSON-RPC request. It reads `request.auth` (via
   Starlette's `has_required_scope()`) to decide which tools and prompts the
   caller is allowed to see and invoke. A tool whose `scopes` are not a subset
   of the caller's granted scopes returns 403.

1. **`AuthErrorMiddleware`** intercepts the outgoing response:

   - Appends `Strict-Transport-Security`, `X-Content-Type-Options`, and
     `Cache-Control: no-store` to every response.
   - On 401, adds
     `WWW-Authenticate: Bearer realm="…", resource_metadata="…/.well-known/oauth-protected-resource", error="invalid_token"`.
   - On 403, adds
     `WWW-Authenticate: Bearer realm="…", resource_metadata="…/.well-known/oauth-protected-resource"`
     (no error code, following RFC 6750 §3.1).

1. Clients that receive a 401 follow the `resource_metadata` URL to
   `GET /.well-known/oauth-protected-resource`, discover the authorization
   server listed in `authorization_servers`, complete the OAuth 2.1 flow, and
   retry with a valid Bearer token.

## Components

### Token Validator

The `TokenValidator` abstract class is the core extension point. Implement it to
connect to your authorization server (JWT verification, token introspection,
etc.).

```python
import hmac
from auth_mcp.resource_server import TokenInfo, TokenValidator


class IntrospectionTokenValidator(TokenValidator):
    """Validates tokens via the authorization server's introspection endpoint."""

    def __init__(self, introspection_url: str, client_id: str) -> None:
        self._introspection_url = introspection_url
        self._client_id = client_id

    async def validate_token(
        self, token: str, resource: str | None = None
    ) -> TokenInfo | None:
        # Call introspection endpoint
        # Return TokenInfo on success, None on failure
        ...
```

`TokenInfo` fields:

- `subject` (str): User identifier
- `scopes` (tuple[str, ...]): Granted scopes (default: empty)
- `expires_at` (int | None): Token expiration timestamp
- `client_id` (str | None): OAuth client identifier
- `audience` (str | None): Intended audience (resource URI)

### Authentication Backend

`OAuthAuthenticationBackend` is a Starlette `AuthenticationBackend` that
extracts and validates Bearer tokens. It produces `AuthCredentials` with scopes
that work directly with `http_mcp`'s `has_required_scope()` calls.

```python
from auth_mcp.resource_server import OAuthAuthenticationBackend

backend = OAuthAuthenticationBackend(
    token_validator=my_validator,
    resource_uri="https://mcp.example.com",
    require_authentication=True,  # default; raises 401 for missing/invalid tokens
)
```

When `require_authentication=False`, unauthenticated requests pass through with
empty credentials. Only use this when you have public tools that should be
accessible without a token.

### Protected Resource Metadata

Serves the RFC 9728 discovery document at
`/.well-known/oauth-protected-resource`. Clients use this to discover which
authorization server to authenticate against.

```python
from auth_mcp.resource_server import ProtectedResourceMetadataEndpoint
from auth_mcp.types import ProtectedResourceMetadata

metadata = ProtectedResourceMetadata(
    resource="https://mcp.example.com",
    authorization_servers=("https://auth.example.com",),
    scopes_supported=("read", "write", "admin"),
)
endpoint = ProtectedResourceMetadataEndpoint(metadata)
```

### WWW-Authenticate Middleware

`AuthErrorMiddleware` intercepts 401/403 responses and adds a `WWW-Authenticate`
header with the `resource_metadata` discovery URL. This tells clients where to
find the authorization server.

```python
from auth_mcp.resource_server import build_www_authenticate_header

# Programmatic header construction
header = build_www_authenticate_header(
    resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
    realm="mcp-server",
    error="invalid_token",
)
# Bearer realm="mcp-server", resource_metadata="https://...", error="invalid_token"
```

All parameter values are sanitized against header injection (CR/LF stripped, `"`
and `\` escaped per RFC 7230).

### Integration Helper

`create_protected_mcp_app()` wires all components into a single Starlette app.

```python
from auth_mcp.resource_server import (
    CORSConfig,
    ProtectedMCPAppConfig,
    create_protected_mcp_app,
)

config = ProtectedMCPAppConfig(
    mcp_server=mcp_server,
    token_validator=my_validator,
    resource_uri="https://mcp.example.com",
    authorization_servers=("https://auth.example.com",),
    scopes_supported=("read", "write"),
    mcp_path="/mcp",                 # MCP endpoint mount path
    realm="my-mcp-server",           # WWW-Authenticate realm
    require_authentication=True,     # enforce auth (default)
    cors=CORSConfig(                 # optional CORS
        allow_origins=("https://client.example.com",),
    ),
)

app = create_protected_mcp_app(config)
```

## Best Practices

### Token Validation

**Use constant-time comparison.** When comparing tokens against stored values,
use `hmac.compare_digest()` instead of `==` to prevent timing side-channel
attacks. JWT libraries handle this internally.

```python
import hmac

# Bad: timing attack vulnerable
if token == stored_token:  # noqa
    ...

# Good: constant-time comparison
if hmac.compare_digest(token.encode(), stored_token.encode()):
    ...
```

**Cache validation results.** If your validator calls a remote introspection
endpoint, cache successful validations with an appropriate TTL to reduce latency
and authorization server load.

**Validate the audience.** Check that the token's `audience` matches your
`resource_uri` to prevent tokens issued for other services from being accepted.

```python
async def validate_token(
    self, token: str, resource: str | None = None
) -> TokenInfo | None:
    payload = decode_jwt(token)
    if payload.get("aud") != resource:
        return None
    ...
```

### Scope Design

**Use narrow, purpose-specific scopes.** Define scopes that map to specific
capabilities rather than broad roles.

```python
# Prefer specific scopes
Tool(func=read_data, inputs=..., output=..., scopes=("data:read",))
Tool(func=write_data, inputs=..., output=..., scopes=("data:write",))

# Avoid overly broad scopes
Tool(func=read_data, inputs=..., output=..., scopes=("admin",))
```

**Require at least one scope per sensitive tool.** Tools without scopes are
accessible to any authenticated (or unauthenticated) user. Always assign scopes
to tools that access or modify protected resources.

**Use `require_authentication=True` (default).** Only set to `False` when you
explicitly need public tools accessible without any token. When `False`, invalid
or expired tokens are silently treated as unauthenticated rather than rejected.

### Deployment

**Always deploy behind HTTPS.** Bearer tokens are transmitted in the
`Authorization` header and must be protected in transit. The library adds
`Strict-Transport-Security` headers, but TLS termination must be configured at
the reverse proxy or load balancer.

**Set specific CORS origins.** Never use `allow_origins=("*",)` with
`allow_credentials=True`. Always list the exact origins that need access.

```python
# Good: specific origins
cors=CORSConfig(allow_origins=("https://app.example.com",))

# Bad: wildcard with credentials
cors=CORSConfig(allow_origins=("*",), allow_credentials=True)
```

**Use the metadata endpoint for discovery.** Clients should fetch
`/.well-known/oauth-protected-resource` to discover the authorization server
rather than hardcoding it. This allows server-side changes without client
updates.

## Use Cases

### MCP Server with External OAuth Provider

Connect to an existing OAuth 2.1 authorization server (Auth0, Keycloak, etc.)
using JWT validation:

```python
import jwt
from auth_mcp.resource_server import TokenInfo, TokenValidator


class JWTTokenValidator(TokenValidator):
    def __init__(self, jwks_url: str, issuer: str, audience: str) -> None:
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._audience = audience

    async def validate_token(
        self, token: str, resource: str | None = None
    ) -> TokenInfo | None:
        try:
            # Fetch JWKS and verify token (use caching in production)
            payload = jwt.decode(
                token,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                # ... JWKS key retrieval
            )
        except jwt.InvalidTokenError:
            return None

        return TokenInfo(
            subject=payload["sub"],
            scopes=tuple(payload.get("scope", "").split()),
            expires_at=payload.get("exp"),
            client_id=payload.get("client_id"),
            audience=payload.get("aud"),
        )


config = ProtectedMCPAppConfig(
    mcp_server=mcp_server,
    token_validator=JWTTokenValidator(
        jwks_url="https://auth.example.com/.well-known/jwks.json",
        issuer="https://auth.example.com",
        audience="https://mcp.example.com",
    ),
    resource_uri="https://mcp.example.com",
    authorization_servers=("https://auth.example.com",),
)

app = create_protected_mcp_app(config)
```

### Mixed Public and Private Tools

Expose some tools publicly while requiring auth for others:

```python
from http_mcp.types import Tool
from http_mcp.server import MCPServer

TOOLS = (
    Tool(func=health_check, inputs=type(None), output=HealthOutput),
    Tool(func=list_models, inputs=type(None), output=ModelsOutput),
    Tool(
        func=run_query,
        inputs=QueryInput,
        output=QueryOutput,
        scopes=("query:execute",),
    ),
    Tool(
        func=manage_users,
        inputs=UserInput,
        output=UserOutput,
        scopes=("admin",),
    ),
)

config = ProtectedMCPAppConfig(
    mcp_server=MCPServer(name="api", version="1.0.0", tools=TOOLS),
    token_validator=my_validator,
    resource_uri="https://mcp.example.com",
    authorization_servers=("https://auth.example.com",),
    require_authentication=False,  # allow public access to unsoped tools
)

app = create_protected_mcp_app(config)
```

With `require_authentication=False`, unauthenticated users see `health_check`
and `list_models`. Authenticated users with the right scopes also see
`run_query` and `manage_users`.

### Browser-Based MCP Client with CORS

Enable cross-origin access for a browser-based client:

```python
from auth_mcp.resource_server import CORSConfig, ProtectedMCPAppConfig

config = ProtectedMCPAppConfig(
    mcp_server=mcp_server,
    token_validator=my_validator,
    resource_uri="https://mcp.example.com",
    authorization_servers=("https://auth.example.com",),
    cors=CORSConfig(
        allow_origins=(
            "https://app.example.com",
            "https://staging.example.com",
        ),
        allow_methods=("GET", "POST"),
        allow_headers=("Authorization", "Content-Type"),
        allow_credentials=True,
    ),
)

app = create_protected_mcp_app(config)
```

## Security Surfaces by Endpoint

### `POST /mcp` -- MCP JSON-RPC Endpoint

| Surface | Details | |---|---| | **Authentication** | Bearer token extracted
from `Authorization` header, validated via `TokenValidator`. Tokens are rejected
if they exceed 2048 characters or contain characters outside the RFC 6750
`b64token` pattern. | | **Authorization** | Scope-based filtering via
Starlette's `has_required_scope()`. Tools/prompts without matching scopes are
hidden from listings and blocked on invocation. | | **Input validation** |
JSON-RPC messages validated by Pydantic. Request body capped at 4 MB.
Content-Type strictly checked (`application/json` only, parameters ignored). | |
**Error handling** | Tool/prompt names truncated to 100 characters in error
messages. Pydantic validation errors sanitized before inclusion in responses. |
| **Response headers** | `X-Content-Type-Options: nosniff`,
`Cache-Control: no-store`,
`Strict-Transport-Security: max-age=31536000; includeSubDomains`. |

### `GET /.well-known/oauth-protected-resource` -- Discovery Endpoint

| Surface | Details | |---|---| | **Authentication** | Subject to the same auth
middleware as `/mcp`. When `require_authentication=True`, this endpoint requires
a valid token. Set to `False` if clients need to discover the authorization
server before authenticating. | | **Input validation** | Only `GET` allowed;
other methods return `405 Method Not Allowed`. | | **Output** | Serialized once
at startup from a frozen `ProtectedResourceMetadata` model. URI fields validated
as HTTP/HTTPS URLs via Pydantic's `AnyHttpUrl`. | | **Response headers** | Same
security headers as `/mcp`. |

### `WWW-Authenticate` Response Header (401/403)

| Surface | Details | |---|---| | **Header injection** | All parameter values
(`realm`, `resource_metadata`, `scope`, `error`, `error_description`) are
sanitized: CR/LF characters stripped, backslash and double-quote escaped per RFC
7230 quoted-string rules. | | **Information disclosure** | Error responses use
generic messages (`"Authentication required"`). The original
`AuthenticationError` message is discarded. Distinct error codes
(`invalid_token` on 401, none on 403) follow RFC 6750 without leaking internal
state. |

### Token Validation Pipeline

| Surface | Details | |---|---| | **Pre-validation** | Tokens are checked
against a 2048-character length limit and the RFC 6750 `b64token` regex before
reaching the `TokenValidator`. Malformed tokens are rejected without calling the
validator. | | **Timing attacks** | The `TokenValidator` ABC documents that
implementations must use constant-time comparison (`hmac.compare_digest()`). The
library does not perform token comparison itself. | | **Logging** | Token values
are never logged. Only `"Token validation failed"` and
`"Malformed or oversized bearer token rejected"` debug messages are emitted. |

### OAuth Types (Request/Response Models)

| Surface | Details | |---|---| | **`TokenRequest`** | `grant_type` restricted
to `Literal["authorization_code", "refresh_token"]`. | |
**`AuthorizationRequest`** | `code_challenge_method` restricted to
`Literal["S256"]` (plain method forbidden per OAuth 2.1). | |
**`ClientRegistrationRequest`** | `redirect_uris` validated as absolute URIs
with HTTPS scheme. HTTP is allowed only for `localhost`, `127.0.0.1`, and `::1`.
| | **`AuthorizationServerMetadata`** | `issuer` must use HTTPS. All endpoint
fields validated as HTTP/HTTPS URLs. | | **Immutability** | All Pydantic models
use `ConfigDict(frozen=True)` to prevent post-construction mutation. |
