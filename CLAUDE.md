# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

**http-mcp** is a lightweight Python library implementing the Model Context
Protocol (MCP) over HTTP and STDIO. It exposes Python functions as tools and
prompts via JSON-RPC, designed for use with Starlette/FastAPI applications.
Published on PyPI as `http-mcp`.

## Common Commands

```bash
# Install dependencies
uv sync

# Run all tests with coverage (90% minimum required)
pytest --cov-report term-missing --cov=src --cov-fail-under=90 tests/

# Run a single test file
pytest tests/test_tools.py

# Run a single test
pytest tests/test_tools.py::test_name -v

# Type checking (strict mode)
mypy .

# Lint (all ruff rules enabled)
ruff check

# Format
ruff format

# Format markdown files
mdformat . --wrap 80

# Full pre-push check (what CI runs)
ruff check && mypy . && pytest --cov-report term-missing --cov=src --cov-fail-under=90 tests/ && mdformat . --wrap 80
```

## Architecture

### Source Layout

Source is in `src/http_mcp/` and `src/auth_mcp/` with `hatchling` as build
backend. The package uses `uv` for dependency management. Both packages ship in
the same wheel (`http-mcp`); `auth_mcp` is available via
`pip install http-mcp[auth]`.

### Core Components

- **`server.py`** — `MCPServer` class: central entry point. Manages
  tools/prompts, handles JSON-RPC dispatch, supports both HTTP and STDIO
  transports. Integrates with Starlette's lifespan for state management.
- **`server_interface.py`** — Abstract base class (`ServerInterface`) that
  `MCPServer` implements.
- **`types/`** — Public API types exported via `http_mcp.types`:
  - `Tool` — Wraps a function with Pydantic input/output schemas. Supports
    sync/async, optional `Arguments[TInputs]` parameter, error handling, and
    authorization scopes.
  - `Prompt` — Interactive templates returning `tuple[PromptMessage, ...]`.
  - `Arguments[T]` — Generic container providing `inputs`, `request`, and
    `get_state_key()` for accessing lifespan state.
  - `NoArguments` — Empty Pydantic model for tools/prompts without parameters.
- **`exceptions.py`** — Exception hierarchy: `BaseError` → `ProtocolError`,
  `ServerError` (with `ToolNotFoundError`, `ToolInvocationError`,
  `PromptNotFoundError`, `PromptInvocationError`), `ArgumentsError`.

### Internal Modules (prefixed with `_`)

- **`_transport_http.py`** / **`_transport_base.py`** — HTTP transport (ASGI,
  4MB max message, content-type validation).
- **`_stdio_transport.py`** — STDIO transport (line-based JSON-RPC over
  stdin/stdout).
- **`_mcp_types/`** — MCP protocol types (capabilities, messages, tools,
  prompts, content). Supported versions: 2025-03-26, 2025-06-18, 2025-11-25.
- **`_json_rcp_types/`** — JSON-RPC message and error types.

### auth_mcp Package (`src/auth_mcp/`)

OAuth 2.1 authorization for MCP servers (Phase 1: Resource Server).

- **`exceptions.py`** — `AuthError` hierarchy: `TokenValidationError`,
  `InsufficientScopeError`, `DiscoveryError`, `RegistrationError`, `PKCEError`.

- **`types/`** — Pydantic models (all frozen, URI-validated):

  - `metadata.py` — `ProtectedResourceMetadata` (RFC 9728),
    `AuthorizationServerMetadata` (RFC 8414). URI fields use `AnyHttpUrl`;
    issuer enforces HTTPS.
  - `oauth.py` — `TokenRequest` (`grant_type` is
    `Literal["authorization_code", "refresh_token"]`), `TokenResponse`,
    `AuthorizationRequest` (`code_challenge_method` is `Literal["S256"]`).
  - `registration.py` — `ClientRegistrationRequest` (redirect URIs validated:
    HTTPS required, HTTP only for localhost), `ClientRegistrationResponse`.
  - `errors.py` — `OAuthErrorResponse`, `WWWAuthenticateChallenge` (header
    values sanitized against injection).

- **`resource_server/`** — Resource Server components:

  - `token_validator.py` — Abstract `TokenValidator` + `TokenInfo` model.
  - `authentication_backend.py` — `OAuthAuthenticationBackend` (Starlette
    backend, `require_authentication=True` by default, token format/length
    validation per RFC 6750).
  - `metadata_endpoint.py` — `ProtectedResourceMetadataEndpoint` ASGI handler
    for `/.well-known/oauth-protected-resource`.
  - `middleware.py` — `AuthErrorMiddleware` (WWW-Authenticate on 401/403),
    `build_www_authenticate_header()`.
  - `integration.py` — `ProtectedMCPAppConfig`, `CORSConfig`,
    `create_protected_mcp_app()`.

- **`authorization_server/`** — Authorization Server components (Phase 2):

  - `client_store.py` — Abstract `ClientStore` for Dynamic Client Registration
    (RFC 7591). Implementations persist registered clients.
  - `metadata_endpoint.py` — `AuthorizationServerMetadataEndpoint` ASGI handler
    for `/.well-known/oauth-authorization-server` (RFC 8414).
  - `registration_endpoint.py` — `DynamicClientRegistrationEndpoint` ASGI
    handler for `/register`. Validates requests, delegates to `ClientStore`,
    returns 201 with `ClientRegistrationResponse`.

### Test Structure

Tests in `tests/` use pytest with pytest-asyncio. A test Starlette app lives in
`tests/app/` with mock tools, prompts, authentication backend, and context.
Tests use `httpx` with Starlette's `TestClient`. Auth tests are in
`tests/auth_mcp/` mirroring the source layout.

## Code Style Conventions

- Python 3.10+ compatible, target 3.13
- 4-space indent, 100-char line length, double quotes, LF line endings
- snake_case for functions/variables, PascalCase for classes
- Comprehensive type hints required (strict mypy)
- Prefer immutable data structures (tuples over lists)
- Prefer functional style: list/dict comprehensions, small focused functions
- Ruff with ALL rules enabled (except D100/D101/D102/D103/D104/D107, EM101);
  S101 (assert) allowed in tests
