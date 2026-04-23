# auth_mcp — OAuth 2.1 Authorization for MCP Servers

`auth_mcp` adds OAuth 2.1 authorization to MCP servers built with `http-mcp`. It
ships in the same wheel and is available via `pip install http-mcp[auth]`.

The package is organized into three areas: **types** (Pydantic models for the
OAuth/MCP authorization protocol), **resource_server** (protecting your MCP
endpoints with bearer token validation), and **authorization_server** (issuing
client registrations so MCP clients can self-register).

## Package Structure

```
src/auth_mcp/
├── __init__.py                        # Re-exports all exception classes
├── exceptions.py                      # AuthError hierarchy
├── types/
│   ├── metadata.py                    # ProtectedResourceMetadata, AuthorizationServerMetadata
│   ├── oauth.py                       # TokenRequest, TokenResponse, AuthorizationRequest
│   ├── registration.py                # ClientRegistrationRequest, ClientRegistrationResponse
│   └── errors.py                      # OAuthErrorResponse, WWWAuthenticateChallenge
├── resource_server/
│   ├── token_validator.py             # Abstract TokenValidator + TokenInfo
│   ├── authentication_backend.py      # OAuthAuthenticationBackend (Starlette)
│   ├── metadata_endpoint.py           # ProtectedResourceMetadataEndpoint (RFC 9728)
│   ├── middleware.py                   # AuthErrorMiddleware, WWW-Authenticate builder
│   └── integration.py                 # ProtectedMCPAppConfig, create_protected_mcp_app()
└── authorization_server/
    ├── client_store.py                # Abstract ClientStore (RFC 7591)
    ├── metadata_endpoint.py           # AuthorizationServerMetadataEndpoint (RFC 8414)
    └── registration_endpoint.py       # DynamicClientRegistrationEndpoint (RFC 7591)
```

______________________________________________________________________

## Exceptions (`auth_mcp.exceptions`)

All exceptions inherit from `AuthError`, which carries a `.message` attribute.

| Exception | When raised | | ------------------------ |
---------------------------------------------- | | `TokenValidationError` |
Token is invalid, expired, or wrong audience | | `InsufficientScopeError` |
Token lacks required scopes (carries `.required_scopes`) | | `DiscoveryError` |
Authorization server discovery failed | | `RegistrationError` | Dynamic Client
Registration rejected | | `PKCEError` | PKCE verification failed |

______________________________________________________________________

## Types (`auth_mcp.types`)

All models use `ConfigDict(frozen=True)` (immutable after creation).

### `metadata.py`

**`ProtectedResourceMetadata`** (RFC 9728) describes an MCP server as a
protected resource. Key fields:

- `resource` — the resource URI (`AnyHttpUrl`)
- `authorization_servers` — tuple of authorization server URIs
- `scopes_supported` — optional tuple of supported scopes

**`AuthorizationServerMetadata`** (RFC 8414) describes an authorization server's
endpoints and capabilities. Key fields:

- `issuer` — must be HTTPS (validated)
- `authorization_endpoint`, `token_endpoint` — required
- `registration_endpoint` — present when Dynamic Client Registration is enabled
- `scopes_supported`, `response_types_supported`, `grant_types_supported` —
  capability advertisements
- `code_challenge_methods_supported` — defaults to `("S256",)` (PKCE)

### `oauth.py`

- **`TokenRequest`** — `grant_type` is
  `Literal["authorization_code", "refresh_token"]`, plus fields for `code`,
  `redirect_uri`, `code_verifier`, `refresh_token`, `client_id`, and `resource`.
- **`TokenResponse`** — `access_token`, `token_type` (default `"Bearer"`),
  `expires_in`, optional `refresh_token` and `scope`.
- **`AuthorizationRequest`** — PKCE-required authorization request with
  `code_challenge` and `code_challenge_method` fixed to `"S256"`.

### `registration.py`

- **`ClientRegistrationRequest`** (RFC 7591) — `redirect_uris` (validated: HTTPS
  required, HTTP only for `localhost`/`127.0.0.1`/`::1`), `client_name`,
  `grant_types`, `response_types`, `token_endpoint_auth_method`.
- **`ClientRegistrationResponse`** — `client_id` (required), optional
  `client_secret`, `client_id_issued_at`, `client_secret_expires_at`, plus the
  echo-back fields from the request.

### `errors.py`

- **`OAuthErrorResponse`** — standard OAuth error body (`error`,
  `error_description`, `error_uri`).
- **`WWWAuthenticateChallenge`** — builds a `WWW-Authenticate: Bearer` header
  value with parameters (`realm`, `resource_metadata`, `scope`, `error`,
  `error_description`). All values are sanitized against header injection (CR/LF
  stripped, backslash and double-quote escaped).

______________________________________________________________________

## Resource Server (`auth_mcp.resource_server`)

Protects your MCP server with OAuth 2.1 bearer token validation. This is **Phase
1** of the auth implementation.

### TokenValidator and TokenInfo

`TokenValidator` is an abstract base class. You implement
`validate_token(token, resource) -> TokenInfo | None` with your own validation
logic (JWT signature check, introspection endpoint call, database lookup, etc.).

`TokenInfo` holds the validated token's `subject`, `scopes` (tuple of strings),
`expires_at`, `client_id`, and `audience`.

```python
from auth_mcp.resource_server import TokenValidator, TokenInfo

class MyTokenValidator(TokenValidator):
    async def validate_token(self, token: str, resource: str | None = None) -> TokenInfo | None:
        # Your validation logic here
        return TokenInfo(subject="user@example.com", scopes=("read", "write"))
```

### OAuthAuthenticationBackend

A Starlette `AuthenticationBackend` that extracts the Bearer token from the
`Authorization` header, validates token format (RFC 6750: max 2048 chars,
alphanumeric + URL-safe characters), and delegates to your `TokenValidator`.

When `require_authentication=True` (default), missing or invalid tokens cause a
401 response. When `False`, unauthenticated requests pass through with empty
credentials — tools/prompts without scope requirements remain accessible.

### ProtectedResourceMetadataEndpoint

ASGI handler serving `/.well-known/oauth-protected-resource` (RFC 9728). Returns
the `ProtectedResourceMetadata` JSON document with security headers
(`X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, HSTS).

### AuthErrorMiddleware

ASGI middleware that:

1. Adds security headers to all HTTP responses.
1. On 401/403 responses, injects a `WWW-Authenticate` header with
   `resource_metadata` discovery parameter per RFC 9728.

### Integration Helper

`create_protected_mcp_app(config)` wires everything together into a Starlette
app:

```python
from auth_mcp.resource_server import (
    ProtectedMCPAppConfig,
    create_protected_mcp_app,
)

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

- MCPServer mounted at `/mcp` (configurable via `mcp_path`)
- Bearer token validation on all requests
- `/.well-known/oauth-protected-resource` metadata endpoint
- Security headers and `WWW-Authenticate` on 401/403
- Optional CORS via
  `cors=CORSConfig(allow_origins=("https://client.example.com",))`

______________________________________________________________________

## Authorization Server (`auth_mcp.authorization_server`)

Enables MCP clients to self-register without manual client ID configuration.
This is **Phase 2** of the auth implementation.

### ClientStore

Abstract base class for persisting registered clients. You implement
`register_client(request) -> ClientRegistrationResponse` with your storage logic
(database, in-memory, etc.).

```python
from auth_mcp.authorization_server import ClientStore
from auth_mcp.types.registration import ClientRegistrationRequest, ClientRegistrationResponse

class MyClientStore(ClientStore):
    async def register_client(
        self, request: ClientRegistrationRequest
    ) -> ClientRegistrationResponse:
        client_id = generate_secure_id()  # Use secrets.token_urlsafe()
        # Persist the client...
        return ClientRegistrationResponse(
            client_id=client_id,
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            response_types=request.response_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
        )
```

An optional `get_client(client_id) -> ClientRegistrationResponse | None` method
defaults to `None` and can be overridden for RFC 7592 client management support.

Security considerations:

- Generate cryptographically random client IDs (`secrets.token_urlsafe(32)`)
- Hash client secrets before storage (never store plaintext)
- Rate-limit the registration endpoint to prevent abuse

### AuthorizationServerMetadataEndpoint

ASGI handler serving `/.well-known/oauth-authorization-server` (RFC 8414).
Returns the `AuthorizationServerMetadata` JSON document. Same security headers
as the resource server metadata endpoint. GET only; other methods return 405.

### DynamicClientRegistrationEndpoint

ASGI handler for `/register` implementing RFC 7591:

- **POST only** — other methods return 405.
- **Validates** `Content-Type: application/json`, body size (64KB max), JSON
  parsing, and Pydantic validation of `ClientRegistrationRequest`.
- **Delegates** to `ClientStore.register_client()`.
- **Returns** 201 Created with `ClientRegistrationResponse` JSON on success.
- **Error responses** use `OAuthErrorResponse` with
  `error: "invalid_client_metadata"` (per RFC 7591 Section 3.2.2).
- Catches `RegistrationError` from the store for application-level rejections.

### Wiring into the Integration Helper

Both authorization server components are optional additions to
`ProtectedMCPAppConfig`:

```python
from auth_mcp.authorization_server import ClientStore
from auth_mcp.resource_server import ProtectedMCPAppConfig, create_protected_mcp_app
from auth_mcp.types.metadata import AuthorizationServerMetadata

as_metadata = AuthorizationServerMetadata(
    issuer="https://auth.example.com",
    authorization_endpoint="https://auth.example.com/authorize",
    token_endpoint="https://auth.example.com/token",
    registration_endpoint="https://auth.example.com/register",
)

config = ProtectedMCPAppConfig(
    mcp_server=mcp_server,
    token_validator=my_validator,
    resource_uri="https://mcp.example.com",
    authorization_servers=("https://auth.example.com",),
    authorization_server_metadata=as_metadata,  # Enables AS metadata endpoint
    client_store=MyClientStore(),                # Enables /register endpoint
)
app = create_protected_mcp_app(config)
```

When `authorization_server_metadata` is set, the app serves
`/.well-known/oauth-authorization-server`. When `client_store` is set, the app
serves `/register`. Both are optional and independent — you can enable either or
both.

______________________________________________________________________

## Full MCP Client Discovery Flow

The MCP spec defines a discovery flow that these components support end-to-end:

1. **Client connects** to the MCP server and gets a 401 with
   `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource"`.

1. **Client fetches** `/.well-known/oauth-protected-resource` and learns which
   authorization servers to use.

1. **Client fetches** `/.well-known/oauth-authorization-server` from the
   authorization server and discovers the `registration_endpoint`,
   `authorization_endpoint`, and `token_endpoint`.

1. **Client registers** via POST to `/register` (Dynamic Client Registration)
   and receives a `client_id`.

1. **Client performs** the OAuth 2.1 authorization code flow with PKCE using the
   discovered endpoints and its new `client_id`.

1. **Client presents** the access token in subsequent MCP requests.

______________________________________________________________________

## Test Structure

Tests mirror the source layout under `tests/auth_mcp/`:

```
tests/auth_mcp/
├── types/                          # Pydantic model validation tests
├── resource_server/
│   ├── test_metadata_endpoint.py   # RFC 9728 metadata endpoint
│   ├── test_authentication_backend.py
│   ├── test_middleware.py
│   └── test_integration.py         # Full app wiring (includes AS + DCR tests)
└── authorization_server/
    ├── test_client_store.py        # Abstract store + mock implementations
    ├── test_metadata_endpoint.py   # RFC 8414 metadata endpoint
    └── test_registration_endpoint.py  # RFC 7591 DCR endpoint
```

All tests use `pytest` with `pytest-asyncio` and Starlette's `TestClient`.
