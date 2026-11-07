# HTTP-MCP

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

# Format markdown files (never `mdformat .` — it rewrites the YAML
# frontmatter in .claude/ into a heading and breaks the agent definitions)
mdformat README.md docs/ --wrap 80 --exclude .claude/

# Full pre-push check (what CI runs)
ruff check && mypy . && pytest --cov-report term-missing --cov=src --cov-fail-under=90 tests/ && mdformat README.md docs/ --wrap 80 --exclude .claude/
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
- **`failures.py`** — Expected failures as values: `ToolNotFound`,
  `PromptNotFound`, `InsufficientScope`, `InvalidArguments`,
  `ToolInvocationFailed`, `PromptInvocationFailed`, `PromptServerFailure`.
- **`exceptions.py`** — What tool and prompt functions raise to report a
  failure: `BaseError` → `ServerError` (with `ToolInvocationError`,
  `PromptInvocationError`). `Tool` and `Prompt` turn them into values at the
  call boundary. Error codes live in `_json_rcp_types/errors.py`; `-32002` was
  retired by the 2026-07-28 revision and must not be reintroduced.

### Internal Modules (prefixed with `_`)

- **`_transport_base.py`** — Single dispatch path for the one supported
  revision. Validates each request's `_meta`, serves `server/discover`, and
  stamps `resultType`/`_meta`/caching hints onto every result. There is
  deliberately no second path: a request must not be able to select weaker
  handling by declaring a different revision.
- **`_transport_http.py`** — HTTP transport (ASGI, 4MB max message, content-type
  validation, `Origin` allowlist, and `MCP-Protocol-Version`/`Mcp-Method`/
  `Mcp-Name`/`Mcp-Param-*` header-to-body validation on every request — this
  check must stay unconditional, see the note in `_validate_request_headers`).
- **`_stdio_transport.py`** — STDIO transport (line-based JSON-RPC over
  stdin/stdout).
- **`_parsing.py`** — `parse_json` and `parse_model`, the adapters that turn the
  exceptions of `json` and pydantic into values. It imports nothing from the
  package, because `types/` depends on it.
- **`_mcp_types/`** — MCP protocol types (capabilities, tools, prompts, content,
  plus `versions`, `meta`, `results`, `discover`, `headers`). The only supported
  version is 2026-07-28; `initialize`, `notifications/initialized`, and `ping`
  do not exist. See the README's "Protocol Version" section.
- **`_json_rcp_types/`** — JSON-RPC message and error types.

### auth_mcp Package (`src/auth_mcp/`)

OAuth 2.1 authorization for MCP servers (Phase 1: Resource Server).

- **`exceptions.py`** — `AuthError` hierarchy: `TokenValidationError`,
  `InsufficientScopeError`, `DiscoveryError`, `PKCEError`.

- **`types/`** — Pydantic models (all frozen, URI-validated):
  - `metadata.py` — `ProtectedResourceMetadata` (RFC 9728),
    `AuthorizationServerMetadata` (RFC 8414). URI fields use `AnyHttpUrl`;
    issuer enforces HTTPS.
  - `oauth.py` — `TokenRequest` (discriminated union on `grant_type` of
    `AuthorizationCodeTokenRequest` and `RefreshTokenRequest`), `TokenResponse`,
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
    (RFC 7591). Implementations persist registered clients, and return
    `RegistrationRejected` to refuse one.
  - `metadata_endpoint.py` — `AuthorizationServerMetadataEndpoint` ASGI handler
    for `/.well-known/oauth-authorization-server` (RFC 8414).
  - `registration_endpoint.py` — `DynamicClientRegistrationEndpoint` ASGI
    handler for `/register`. Validates requests, delegates to `ClientStore`,
    returns 201 with `ClientRegistrationResponse`.

### Test Structure

Tests in `tests/` use pytest with pytest-asyncio. Shared fixtures live in
`tests/fixtures/` with mock tools, prompts, authentication backend, and context;
`tests/fixtures/protocol.py` holds `MCPTestClient`, which completes the request
envelope so individual tests stay about the behaviour they exercise. Tests use
`httpx2` with Starlette's `TestClient`. Auth tests are in `tests/auth_mcp/`
mirroring the source layout.

## Code Style Conventions

- Python 3.10+ compatible, target 3.13
- 4-space indent, 100-char line length, double quotes, LF line endings
- snake_case for functions/variables, PascalCase for classes
- Comprehensive type hints required (strict mypy)
- Prefer immutable data structures (tuples over lists)
- Prefer functional style: list/dict comprehensions, small focused functions
- Ruff with ALL rules enabled (except D100/D101/D102/D103/D104/D107, EM101);
  S101 (assert) allowed in tests

  https://alex.draftist.io/blog/the-bedrock-of-software-design-ycqvcedsj

### Python Domain Safety & ADT Principles

When designing, writing, or refactoring Python code, you must strictly enforce domain safety and explicit contracts using Algebraic Data Type (ADT) principles. Rely on Python's modern typing system (Python 3.10+) and static type checkers (`mypy` or `pyright`) to enforce these rules.

#### 1. Make Invalid States Unrepresentable (Sum Types)

Never use loose collections of primitive types, boolean flags, or optional fields to model mutually exclusive states.

- **Action:** Build Discriminated Unions using `@dataclass` and `typing.Literal`. Define variants that strictly bind required data to specific states, completely preventing invalid combinations from compiling.
- **Example Pattern:**

  ```python
  from dataclasses import dataclass
  from typing import Literal

  @dataclass
  class AnonymousUser:
      type: Literal["anonymous"]

  @dataclass
  class AuthenticatedUser:
      type: Literal["authenticated"]
      user_id: str
      role: str

  User = AnonymousUser | AuthenticatedUser
  ```

#### 2. Require Exhaustive Pattern Matching

Every valid state must be handled explicitly without assumptions. Do not rely on implicit fall-throughs.

- **Action:** Process Union types using `match`/`case` statements.
- **Action:** You MUST use `typing.assert_never` in the default case (`case _ as unreachable:`) to force static type checkers to throw an error if a variant is added to the Union but missing from the match block. Do not use generic catch-all branches for domain logic.
- **Example Pattern:**

  ```python
  from typing import assert_never

  def get_greeting(user: User) -> str:
      match user:
          case AnonymousUser():
              return "Hello, guest."
          case AuthenticatedUser(user_id=uid, role=role):
              return f"Welcome back, {role} {uid}."
          case _ as unreachable:
              assert_never(unreachable)
  ```

#### 3. Make Errors Part of the Contract (Errors as Values)

Do not throw or catch exceptions (`try/except`) for expected, recoverable domain failures (e.g., invalid input, missing records, business rule violations). Exceptions are strictly for fatal, unrecoverable crashes.

- **Action:** Expose failures in the function signature by returning a Union of the success type and a specific error dataclass (e.g., `SuccessType | ErrorType`).
- **Action:** Force the caller to handle the error explicitly via pattern matching.

#### 4. Give Absence an Explicit Type

Never rely on implicit `None` or undocumented missing data.

- **Action:** If a value can be absent, type it explicitly using `T | None`.
- **Action:** The caller must use a `match` statement or strict `if val is not None` checks to safely unwrap and handle the absent state.

#### 5. Match Multiple Inputs Simultaneously

Avoid deep nested `if/else` chains when calculating outcomes based on multiple variables.

- **Action:** Group the interdependent variables into a tuple and pattern-match on their combinations simultaneously. Let the type-checker ensure no edge case in the matrix of combinations is forgotten.
- **Example Pattern:**
  ```python
  def calculate_shipping_days(destination: Literal["domestic", "international"],
                              speed: Literal["standard", "express"]) -> int:
      match (destination, speed):
          case ("domestic", "standard"):
              return 3
          case ("domestic", "express"):
              return 1
          case ("international", "standard"):
              return 10
          case ("international", "express"):
              return 3
          case _ as unreachable:
              assert_never(unreachable)
  ```

#### 6. Type-Checker Driven Development

Domain updates must predictably cascade through the codebase. When modifying the domain (e.g., adding a new variant to a Union), do not search manually for places to update.

- **Action:** Add the variant to the type definition, run the type checker (`mypy` or `pyright`), and use the resulting `assert_never` exhaustiveness errors as a checklist to update the logic everywhere that type is consumed.
