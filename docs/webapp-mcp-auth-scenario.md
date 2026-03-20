# Scenario: Web App User Accessing Data Through an MCP Client

## The Setup

You have a **web application** (e.g. a project management tool, a CRM, an
internal dashboard) that users already sign into via a third-party identity
provider — Google, Azure AD, or Bitbucket. Now you want to expose some of that
web app's data through an **MCP server** so users can access it from MCP clients
like Claude Desktop, Cursor, or a custom AI agent.

The key constraint: the MCP client should only see data the user is already
authorized to see in the web app. The user should not have to create a separate
account or manage API keys — their existing login should carry over.

## The Actors

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────────────┐
│  MCP Client  │     │   MCP Server    │     │       Web App           │
│ (Claude,     │────▶│ (http-mcp +     │────▶│  (your existing app)    │
│  Cursor,     │     │  auth_mcp)      │     │                         │
│  custom)     │     │                 │     │  Identity Providers:    │
│              │     │                 │     │  - Google               │
└─────────────┘     └─────────────────┘     │  - Azure AD             │
                                             │  - Bitbucket            │
                                             └─────────────────────────┘
```

- **MCP Client** — the tool the user runs (Claude Desktop, Cursor, etc.). It
  speaks the MCP protocol and needs an access token to call the MCP server.
- **MCP Server** — your `http-mcp` server with `auth_mcp`. It exposes tools that
  read/write data from the web app. It validates tokens on every request.
- **Web App** — the existing application. It already has OAuth/OIDC login with
  Google, Azure AD, or Bitbucket. It may also serve as (or sit behind) the
  authorization server that issues tokens.

## How It Works End-to-End

### Step 1: User Configures the MCP Server in Their Client

The user adds the MCP server URL to their MCP client configuration. For example,
in Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-webapp": {
      "url": "https://mcp.myapp.com/mcp"
    }
  }
}
```

No client ID, no API key — just the URL. The MCP client will discover everything
else automatically.

### Step 2: MCP Client Discovers the Auth Flow

When the MCP client first connects, the following happens automatically (the
user sees none of this plumbing):

```
MCP Client                          MCP Server
    │                                    │
    │─── POST /mcp (tools/list) ────────▶│
    │                                    │
    │◀── 401 Unauthorized ──────────────│
    │    WWW-Authenticate: Bearer        │
    │    resource_metadata="https://     │
    │    mcp.myapp.com/.well-known/      │
    │    oauth-protected-resource"       │
    │                                    │
    │─── GET /.well-known/              │
    │    oauth-protected-resource ──────▶│
    │                                    │
    │◀── 200 OK ────────────────────────│
    │    {                               │
    │      "resource": "https://...",    │
    │      "authorization_servers":      │
    │        ["https://auth.myapp.com"], │
    │      "scopes_supported":           │
    │        ["read", "write"]           │
    │    }                               │
    │                                    │
```

The MCP client now knows to talk to `https://auth.myapp.com` for authorization.
It fetches the authorization server metadata:

```
MCP Client                          MCP Server (or Auth Server)
    │                                    │
    │─── GET /.well-known/              │
    │    oauth-authorization-server ────▶│
    │                                    │
    │◀── 200 OK ────────────────────────│
    │    {                               │
    │      "issuer": "https://...",      │
    │      "authorization_endpoint":     │
    │        "https://auth.myapp.com/    │
    │         authorize",                │
    │      "token_endpoint":             │
    │        "https://auth.myapp.com/    │
    │         token",                    │
    │      "registration_endpoint":      │
    │        "https://auth.myapp.com/    │
    │         register"                  │
    │    }                               │
    │                                    │
```

### Step 3: MCP Client Registers Itself (Dynamic Client Registration)

The MCP client self-registers. This is the RFC 7591 flow that the
`authorization_server` package enables:

```
MCP Client                          MCP Server
    │                                    │
    │─── POST /register ────────────────▶│
    │    {                               │
    │      "redirect_uris":             │
    │        ["http://localhost:9876/    │
    │          callback"],               │
    │      "client_name": "Claude",      │
    │      "grant_types":               │
    │        ["authorization_code"],     │
    │      "token_endpoint_auth_method": │
    │        "none"                      │
    │    }                               │
    │                                    │
    │◀── 201 Created ──────────────────│
    │    {                               │
    │      "client_id": "dyn_abc123...", │
    │      "redirect_uris": [...],       │
    │      ...                           │
    │    }                               │
    │                                    │
```

Note the `redirect_uris` uses `http://localhost:...` — MCP clients are typically
desktop apps that spin up a temporary local HTTP server to receive the OAuth
callback. The `auth_mcp` registration types allow HTTP for localhost
specifically for this reason.

### Step 4: User Logs In (the Only Part the User Sees)

The MCP client opens the user's browser to the authorization endpoint. This is
where the three identity provider options come in:

```
MCP Client                Browser                    Auth Server
    │                        │                           │
    │── open browser ───────▶│                           │
    │   https://auth.myapp   │                           │
    │   .com/authorize?      │                           │
    │   client_id=dyn_abc123 │                           │
    │   &redirect_uri=http://│                           │
    │   localhost:9876/cb    │                           │
    │   &code_challenge=...  │                           │
    │   &scope=read+write    │                           │
    │                        │── GET /authorize ────────▶│
    │                        │                           │
    │                        │◀─ Login page ────────────│
    │                        │   ┌──────────────────┐    │
    │                        │   │ Sign in to MyApp │    │
    │                        │   │                  │    │
    │                        │   │ [Google]         │    │
    │                        │   │ [Azure AD]       │    │
    │                        │   │ [Bitbucket]      │    │
    │                        │   └──────────────────┘    │
    │                        │                           │
    │                        │   (user clicks Google)    │
    │                        │                           │
    │                        │──▶ Google OIDC login ──▶  │
    │                        │◀── Google callback ◀──    │
    │                        │                           │
    │                        │◀─ 302 redirect ─────────│
    │                        │   http://localhost:9876/  │
    │                        │   cb?code=xyz789          │
    │                        │                           │
    │◀── code=xyz789 ───────│                           │
    │                        │                           │
```

The user sees a familiar login page — the same one they use for the web app.
They pick Google (or Azure AD, or Bitbucket), authenticate, and the browser
redirects back to the MCP client's localhost callback with an authorization
code.

### Step 5: MCP Client Exchanges Code for Token

```
MCP Client                          Auth Server
    │                                    │
    │─── POST /token ───────────────────▶│
    │    grant_type=authorization_code   │
    │    code=xyz789                     │
    │    code_verifier=... (PKCE)        │
    │    client_id=dyn_abc123            │
    │    redirect_uri=http://localhost   │
    │      :9876/cb                      │
    │                                    │
    │◀── 200 OK ────────────────────────│
    │    {                               │
    │      "access_token": "eyJhb...",   │
    │      "token_type": "Bearer",       │
    │      "expires_in": 3600,           │
    │      "refresh_token": "rt_...",    │
    │      "scope": "read write"         │
    │    }                               │
    │                                    │
```

### Step 6: MCP Client Uses the Token

From now on, the MCP client includes the access token in every request. The MCP
server validates it and scopes the response to what the user can see:

```
MCP Client                          MCP Server
    │                                    │
    │─── POST /mcp ─────────────────────▶│
    │    Authorization: Bearer eyJhb...  │
    │    {"jsonrpc":"2.0",               │
    │     "method":"tools/call",         │
    │     "params":{"name":"get_tasks"}, │
    │     "id":1}                        │
    │                                    │
    │    ┌─────────────────────────────┐ │
    │    │ TokenValidator:             │ │
    │    │ 1. Decode JWT               │ │
    │    │ 2. Verify signature         │ │
    │    │ 3. Check expiry             │ │
    │    │ 4. Extract user + scopes    │ │
    │    │ 5. Return TokenInfo(        │ │
    │    │      subject="user@...",    │ │
    │    │      scopes=("read",),      │ │
    │    │      client_id="dyn_abc123")│ │
    │    └─────────────────────────────┘ │
    │                                    │
    │◀── 200 OK ────────────────────────│
    │    {"jsonrpc":"2.0",               │
    │     "result":{"content":[...]},    │
    │     "id":1}                        │
    │                                    │
```

## Architecture Options

There are two ways to set this up depending on whether your web app already has
a full OAuth authorization server or not.

### Option A: Web App as Both Auth Server and Resource

Your web app already issues tokens (e.g. it runs an OAuth provider like Django
OAuth Toolkit, Auth0 tenant, or Keycloak). The MCP server is a separate service
that validates those same tokens.

```
                 ┌─────────────────────────┐
                 │     Web App / Auth       │
                 │                          │
                 │  /.well-known/oauth-     │
                 │    authorization-server  │
                 │  /authorize              │
 ┌───────────┐   │  /token                  │   ┌─────────────┐
 │ MCP Client│──▶│  /register               │   │  Database    │
 │           │   │                          │──▶│  (users,     │
 │           │   └──────────┬───────────────┘   │   projects,  │
 │           │              │ identity          │   tasks...)   │
 │           │              │ federation        │             │
 │           │   ┌──────────▼───────────────┐   └─────────────┘
 │           │──▶│     MCP Server           │         │
 │           │   │  (http-mcp + auth_mcp)   │─────────┘
 │           │   │                          │  reads data using
 └───────────┘   │  Validates tokens from   │  the user's identity
                 │  the web app's auth      │
                 └──────────────────────────┘
```

In this setup, the MCP server's `TokenValidator` validates JWTs issued by the
web app's auth server (checking the signature with the auth server's public
keys). The MCP server and web app share the same database or the MCP server
calls the web app's internal APIs to fetch data on behalf of the authenticated
user.

### Option B: MCP Server as Its Own Auth Server (Proxy Pattern)

Your web app does not have its own OAuth server — it just uses
Google/Azure/Bitbucket for login. The MCP server acts as the authorization
server itself, proxying the identity provider login.

```
 ┌───────────┐   ┌──────────────────────────────────┐
 │ MCP Client│──▶│         MCP Server                │
 │           │   │   (http-mcp + auth_mcp)           │
 │           │   │                                    │
 │           │   │   /.well-known/oauth-              │
 │           │   │     authorization-server           │
 │           │   │   /.well-known/oauth-              │
 │           │   │     protected-resource             │
 │           │   │   /register  (DCR)                 │
 │           │   │   /authorize ──┐                   │
 │           │   │   /token       │                   │
 │           │   │   /mcp         │                   │
 └───────────┘   └────────────────┼───────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │   Identity Provider        │
                    │   (Google / Azure AD /     │
                    │    Bitbucket)              │
                    └───────────────────────────┘
```

In this setup, the MCP server handles the full OAuth flow. When the user hits
`/authorize`, the MCP server redirects to the chosen identity provider (Google,
Azure AD, or Bitbucket). After the user authenticates there, the provider
redirects back to the MCP server, which issues its own access token (a JWT
signed with its own key). The `TokenValidator` then validates these self-issued
tokens.

This is the more self-contained option — the MCP server is both the
authorization server and the resource server.

## What `auth_mcp` Handles vs. What You Build

| Component | `auth_mcp` provides | You implement | | --- | --- | --- | | Token
validation on MCP requests | `TokenValidator` abstract class,
`OAuthAuthenticationBackend`, `AuthErrorMiddleware` | `TokenValidator` subclass
(JWT decode, signature check, introspection call) | | Protected resource
discovery | `ProtectedResourceMetadataEndpoint` | Configuration only | | AS
metadata discovery | `AuthorizationServerMetadataEndpoint` | Configuration only
| | Dynamic Client Registration | `DynamicClientRegistrationEndpoint`,
`ClientStore` abstract class | `ClientStore` subclass (database persistence, ID
generation) | | `/authorize` endpoint | Types (`AuthorizationRequest`) | The
endpoint itself: render login page, federate to Google/Azure/Bitbucket, issue
authorization code | | `/token` endpoint | Types (`TokenRequest`,
`TokenResponse`) | The endpoint itself: validate authorization code, verify
PKCE, issue access + refresh tokens | | Identity provider federation | Nothing
(out of scope) | OIDC integration with Google/Azure/Bitbucket (e.g. via
`authlib`, `python-social-auth`) | | Scope enforcement per tool | Built into
`http_mcp` (`Tool(scopes=(...))`) | Define which scopes each tool requires | |
User-to-data authorization | Nothing (app-specific) | Map the token's `subject`
to the user's data in your app |

## Implementation Example (Option B)

Here is a sketch of how you would wire this up with `auth_mcp` for a web app
that uses Google, Azure AD, and Bitbucket for login.

### 1. Define Your Tools

```python
from http_mcp.types import Tool, Arguments
from pydantic import BaseModel

class TaskListInput(BaseModel):
    project_id: str

class TaskOutput(BaseModel):
    tasks: list[dict]

async def list_tasks(args: Arguments[TaskListInput]) -> TaskOutput:
    user_id = args.request.user.display_name  # From the validated token
    tasks = await db.get_tasks(
        project_id=args.inputs.project_id,
        user_id=user_id,  # Only this user's tasks
    )
    return TaskOutput(tasks=tasks)

tools = (
    Tool(
        func=list_tasks,
        inputs=TaskListInput,
        output=TaskOutput,
        scopes=("read",),  # Requires "read" scope
    ),
)
```

### 2. Implement TokenValidator

```python
import jwt
from auth_mcp.resource_server import TokenValidator, TokenInfo

class JWTTokenValidator(TokenValidator):
    def __init__(self, public_key: str, issuer: str) -> None:
        self._public_key = public_key
        self._issuer = issuer

    async def validate_token(
        self, token: str, resource: str | None = None
    ) -> TokenInfo | None:
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=resource,
            )
            return TokenInfo(
                subject=payload["sub"],
                scopes=tuple(payload.get("scope", "").split()),
                expires_at=payload.get("exp"),
                client_id=payload.get("client_id"),
                audience=resource,
            )
        except jwt.InvalidTokenError:
            return None
```

### 3. Implement ClientStore

```python
import secrets
from auth_mcp.authorization_server import ClientStore
from auth_mcp.types.registration import (
    ClientRegistrationRequest,
    ClientRegistrationResponse,
)

class DatabaseClientStore(ClientStore):
    async def register_client(
        self, request: ClientRegistrationRequest
    ) -> ClientRegistrationResponse:
        client_id = secrets.token_urlsafe(32)
        # Persist to your database...
        await db.save_client(
            client_id=client_id,
            redirect_uris=request.redirect_uris,
            client_name=request.client_name,
        )
        return ClientRegistrationResponse(
            client_id=client_id,
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            response_types=request.response_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
        )
```

### 4. Wire Everything Together

```python
from http_mcp.server import MCPServer
from auth_mcp.resource_server import (
    ProtectedMCPAppConfig,
    create_protected_mcp_app,
)
from auth_mcp.types.metadata import AuthorizationServerMetadata

mcp_server = MCPServer(
    name="myapp-mcp",
    version="1.0.0",
    tools=tools,
)

as_metadata = AuthorizationServerMetadata(
    issuer="https://mcp.myapp.com",
    authorization_endpoint="https://mcp.myapp.com/authorize",
    token_endpoint="https://mcp.myapp.com/token",
    registration_endpoint="https://mcp.myapp.com/register",
    scopes_supported=("read", "write"),
)

config = ProtectedMCPAppConfig(
    mcp_server=mcp_server,
    token_validator=JWTTokenValidator(
        public_key=PUBLIC_KEY,
        issuer="https://mcp.myapp.com",
    ),
    resource_uri="https://mcp.myapp.com",
    authorization_servers=("https://mcp.myapp.com",),
    scopes_supported=("read", "write"),
    authorization_server_metadata=as_metadata,
    client_store=DatabaseClientStore(),
)

app = create_protected_mcp_app(config)

# You still need to add /authorize and /token endpoints yourself:
# app.add_route("/authorize", authorize_endpoint)
# app.add_route("/token", token_endpoint)
```

### 5. Build `/authorize` and `/token` (You Implement These)

The `/authorize` endpoint is where the three identity providers appear. A
simplified sketch:

```python
from starlette.responses import RedirectResponse

async def authorize_endpoint(request):
    # Parse the OAuth authorization request params
    client_id = request.query_params["client_id"]
    redirect_uri = request.query_params["redirect_uri"]
    code_challenge = request.query_params["code_challenge"]
    scope = request.query_params.get("scope", "")

    # Store the OAuth request in the session, then show login page
    # or redirect to chosen provider:
    #
    #   Google:    redirect to accounts.google.com/o/oauth2/v2/auth
    #   Azure AD:  redirect to login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize
    #   Bitbucket: redirect to bitbucket.org/site/oauth2/authorize
    #
    # After the provider callback, generate an authorization code,
    # store it with the code_challenge, and redirect back:
    #
    #   return RedirectResponse(f"{redirect_uri}?code={auth_code}")
```

The `/token` endpoint exchanges the authorization code for your own JWT:

```python
async def token_endpoint(request):
    form = await request.form()
    code = form["code"]
    code_verifier = form["code_verifier"]

    # 1. Look up stored authorization code
    # 2. Verify PKCE: SHA256(code_verifier) == stored code_challenge
    # 3. Issue a JWT signed with your private key
    # 4. Return TokenResponse
```

## Provider-Specific Notes

### Google

- OIDC discovery: `https://accounts.google.com/.well-known/openid-configuration`
- Provides `email`, `name`, `picture` in the ID token.
- Use the Google user's `sub` claim as the stable user identifier — email can
  change.

### Azure AD

- OIDC discovery:
  `https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration`
- Supports single-tenant and multi-tenant configurations.
- Provides `oid` (object ID) as stable identifier. `preferred_username` is the
  UPN.
- Can map Azure AD groups to MCP scopes for fine-grained access control.

### Bitbucket

- OAuth 2.0 (not full OIDC). Authorization endpoint:
  `https://bitbucket.org/site/oauth2/authorize`
- Token endpoint: `https://bitbucket.org/site/oauth2/access_token`
- Use the Bitbucket user API (`/2.0/user`) to get the user's UUID after token
  exchange.
- Bitbucket tokens are shorter-lived — consider using refresh tokens.

## Security Considerations

- **Token scoping**: Map identity provider claims to MCP scopes. A user who can
  only read in the web app should get `read` scope, not `write`.
- **Token lifetime**: Keep access tokens short-lived (5-15 minutes) and use
  refresh tokens for longer sessions. MCP clients handle token refresh
  automatically.
- **PKCE is mandatory**: `auth_mcp` enforces `S256` code challenge method. This
  prevents authorization code interception attacks, which is critical for
  desktop MCP clients using localhost redirects.
- **Redirect URI validation**: Only `http://localhost:*` is allowed for HTTP
  redirects. All other redirect URIs must be HTTPS. This is enforced by
  `ClientRegistrationRequest` validation.
- **User data isolation**: Your tools must filter data based on the
  authenticated user's identity from `TokenInfo.subject`. The MCP server
  validates the token, but your tool code is responsible for only returning data
  the user is authorized to see.
