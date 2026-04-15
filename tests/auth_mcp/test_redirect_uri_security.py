"""Security regression tests for redirect-URI validation.

These tests codify the security invariants of the OAuth 2.1 dynamic client
registration redirect-URI validation (RFC 7591 / RFC 8252). They guard
against silent regressions in the denylist, localhost checks, custom-scheme
allowlist plumbing, and exotic URI edge cases.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from auth_mcp.authorization_server.client_store import ClientStore
from auth_mcp.authorization_server.registration_endpoint import (
    DynamicClientRegistrationEndpoint,
)
from auth_mcp.types.registration import (
    DISALLOWED_REDIRECT_SCHEMES,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockClientStore(ClientStore):
    """Minimal store that echoes back the registration request."""

    _counter: int = 0

    async def register_client(
        self,
        request: ClientRegistrationRequest,
    ) -> ClientRegistrationResponse:
        self._counter += 1
        return ClientRegistrationResponse(
            client_id=f"client_{self._counter}",
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            response_types=request.response_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
        )


def _endpoint_client(
    allowed_custom_redirect_schemes: tuple[str, ...] = (),
) -> TestClient:
    endpoint = DynamicClientRegistrationEndpoint(
        _MockClientStore(),
        allowed_custom_redirect_schemes=allowed_custom_redirect_schemes,
    )
    return TestClient(endpoint)


def _model_validate(
    uris: tuple[str, ...],
    allowed: frozenset[str] | None = None,
) -> ClientRegistrationRequest:
    ctx = (
        {"allowed_custom_redirect_schemes": allowed}
        if allowed is not None
        else None
    )
    return ClientRegistrationRequest.model_validate(
        {"redirect_uris": uris},
        context=ctx,
    )


# ===================================================================
# 1. Constants / export stability
# ===================================================================

_EXPECTED_MINIMUM_DENYLIST: frozenset[str] = frozenset(
    {
        "javascript",
        "data",
        "file",
        "vbscript",
        "about",
        "blob",
        "mailto",
        "tel",
        "ws",
        "wss",
        "ftp",
        "ftps",
        "intent",
        "view-source",
    },
)


def test_disallowed_schemes_is_frozenset() -> None:
    """DISALLOWED_REDIRECT_SCHEMES must be immutable (frozenset)."""
    assert isinstance(DISALLOWED_REDIRECT_SCHEMES, frozenset)


def test_disallowed_schemes_contains_minimum_set() -> None:
    """Guard against accidental removal of known-dangerous schemes."""
    missing = _EXPECTED_MINIMUM_DENYLIST - DISALLOWED_REDIRECT_SCHEMES
    assert not missing, f"Schemes removed from denylist: {sorted(missing)}"


# ===================================================================
# 2. Denylist enforcement (hard invariant)
# ===================================================================

@pytest.mark.parametrize("scheme", sorted(DISALLOWED_REDIRECT_SCHEMES))
def test_denylist_rejects_even_when_allowlisted(scheme: str) -> None:
    """Every scheme in the denylist is rejected at validation level.

    Even when the caller passes it in allowed_custom_redirect_schemes.
    """
    uri = f"{scheme}://anything.example.com/path"
    with pytest.raises(ValidationError, match="scheme is not allowed"):
        _model_validate(
            (uri,),
            allowed=frozenset({scheme}),
        )


@pytest.mark.parametrize(
    "uri",
    [
        "JavaScript:alert(1)",
        "JAVASCRIPT:ALERT(1)",
        "DATA:text/html,<h1>hi</h1>",
        "Data:text/html,<script>x</script>",
        "Intent://evil#Intent;scheme=http;end",
        "INTENT://evil#Intent;scheme=http;end",
        "View-Source:https://example.com",
        "VIEW-SOURCE:https://example.com",
        "VbScript:MsgBox(1)",
    ],
    ids=[
        "JavaScript-title",
        "JAVASCRIPT-upper",
        "DATA-upper",
        "Data-mixed",
        "Intent-title",
        "INTENT-upper",
        "View-Source-title",
        "VIEW-SOURCE-upper",
        "VbScript-mixed",
    ],
)
def test_denylist_case_insensitive(uri: str) -> None:
    """Denylist comparison is case-insensitive — mixed/upper case rejected."""
    with pytest.raises(ValidationError, match="scheme is not allowed"):
        _model_validate((uri,))


@pytest.mark.parametrize(
    "uri",
    [
        # Whitespace around URI — urlparse strips leading whitespace from
        # the scheme on some Python versions; trailing is part of the path.
        "  javascript:alert(1)",
        "javascript:alert(1)  ",
    ],
    ids=["leading-whitespace", "trailing-whitespace"],
)
def test_denylist_whitespace_variants(uri: str) -> None:
    """URIs with surrounding whitespace are still rejected or fail.

    Either outcome is safe — the URI never passes validation.
    """
    with pytest.raises(ValidationError):
        _model_validate((uri,))


# ===================================================================
# 3. Localhost check strictness
# ===================================================================

@pytest.mark.parametrize(
    "uri",
    [
        "http://127.1/",
        "http://0x7f000001/",
        "http://2130706433/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://localhost.attacker.com/",
        "http://attacker.com#@localhost/",
        "http://user@localhost@attacker.com/",
    ],
    ids=[
        "127.1-short",
        "hex-ip",
        "decimal-ip",
        "ipv4-mapped-ipv6",
        "0.0.0.0",  # noqa: S104
        "localhost-subdomain",
        "fragment-at-localhost",
        "userinfo-bypass-attempt",
    ],
)
def test_http_localhost_aliases_rejected(uri: str) -> None:
    """HTTP redirect URIs with localhost aliases are rejected.

    The validator only allows literal ``localhost``, ``127.0.0.1``,
    and ``::1``.
    """
    with pytest.raises(ValidationError):
        _model_validate((uri,))


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost/",
        "http://localhost:3000/callback",
        "http://localhost/path?q=1",
        "http://LOCALHOST/",
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/callback",
        "http://[::1]/",
        "http://[::1]:9090/callback",
    ],
    ids=[
        "localhost-bare",
        "localhost-port",
        "localhost-path-query",
        "LOCALHOST-upper",
        "127.0.0.1-bare",
        "127.0.0.1-port",
        "ipv6-loopback",
        "ipv6-loopback-port",
    ],
)
def test_http_localhost_valid_forms_accepted(uri: str) -> None:
    """Canonical localhost forms are accepted for HTTP redirect URIs."""
    result = _model_validate((uri,))
    assert uri in result.redirect_uris


# ===================================================================
# 4. Allowlist plumbing — end-to-end through endpoint
# ===================================================================

def test_e2e_custom_scheme_cursor_accepted() -> None:
    """Custom scheme accepted end-to-end when allowlisted at init."""
    client = _endpoint_client(allowed_custom_redirect_schemes=("cursor",))
    response = client.post(
        "/",
        json={
            "redirect_uris": [
                "cursor://anysphere.cursor-mcp/oauth/callback",
            ],
        },
    )
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data["redirect_uris"] == [
        "cursor://anysphere.cursor-mcp/oauth/callback",
    ]


def test_e2e_reverse_dns_custom_scheme_accepted() -> None:
    """Reverse-DNS custom scheme (RFC 8252 style) accepted."""
    client = _endpoint_client(
        allowed_custom_redirect_schemes=("com.example.app",),
    )
    response = client.post(
        "/",
        json={
            "redirect_uris": [
                "com.example.app://oauth/callback",
            ],
        },
    )
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data["redirect_uris"] == ["com.example.app://oauth/callback"]


def test_e2e_custom_scheme_not_in_allowlist_rejected() -> None:
    """Custom scheme NOT in the allowlist is rejected with helpful msg."""
    client = _endpoint_client(allowed_custom_redirect_schemes=("cursor",))
    response = client.post(
        "/",
        json={
            "redirect_uris": [
                "vscode://ms-vscode.mcp/oauth/callback",
            ],
        },
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert "explicitly allowed by the server" in data["error_description"]


def test_endpoint_init_rejects_disallowed_scheme_case_insensitive() -> None:
    """Endpoint __init__ rejects a denylist scheme regardless of case."""
    with pytest.raises(ValueError, match="must not include disallowed"):
        DynamicClientRegistrationEndpoint(
            _MockClientStore(),
            allowed_custom_redirect_schemes=("INTENT",),
        )


@pytest.mark.parametrize(
    "reserved",
    ["HTTP", "Http", "http", "HTTPS", "Https", "https"],
    ids=str,
)
def test_endpoint_init_rejects_http_https_any_case(
    reserved: str,
) -> None:
    """Endpoint __init__ rejects http/https in allowlist (any case)."""
    with pytest.raises(ValueError, match="must not include"):
        DynamicClientRegistrationEndpoint(
            _MockClientStore(),
            allowed_custom_redirect_schemes=(reserved,),
        )


# ===================================================================
# 5. Exotic URI shapes
# ===================================================================

def test_empty_redirect_uri_rejected() -> None:
    with pytest.raises(ValidationError, match="must be an absolute URI"):
        _model_validate(("",))


def test_relative_uri_rejected() -> None:
    with pytest.raises(ValidationError, match="must be an absolute URI"):
        _model_validate(("/callback",))


def test_scheme_only_uri_rejected_for_custom_scheme() -> None:
    """A URI with only a scheme (no netloc, no path) is rejected."""
    with pytest.raises(ValidationError, match="must be an absolute URI"):
        _model_validate(("cursor:",), allowed=frozenset({"cursor"}))


def test_query_and_fragment_preserved_on_success() -> None:
    """Query and fragment in valid HTTPS URIs survive validation."""
    uri = "https://c.example.com/cb?x=1#y=2"
    result = _model_validate((uri,))
    assert result.redirect_uris == (uri,)


def test_mixed_valid_and_invalid_uris_all_rejected() -> None:
    """One invalid URI in the tuple causes the whole list to fail."""
    with pytest.raises(ValidationError):
        _model_validate((
            "https://good.example.com/callback",
            "javascript:alert(1)",
        ))


def test_crlf_injection_uri_rejected_or_safe_json() -> None:
    """URI with embedded CR/LF is rejected or serialized safely.

    Even if somehow accepted, JSON serialization escapes control chars,
    so header injection via the error body is not possible.
    """
    uri = "https://example.com/\r\nInjected-Header: x"
    client = _endpoint_client()
    response = client.post("/", json={"redirect_uris": [uri]})
    # The response MUST be valid JSON regardless.
    data = response.json()
    assert isinstance(data, dict)
    # If the server rejected it (most likely), verify error shape.
    if response.status_code != HTTPStatus.CREATED:
        assert data["error"] == "invalid_client_metadata"
    # Confirm the raw body does not contain bare CRLF that could split
    # HTTP headers (the JSON encoder escapes \r\n).
    assert b"\r\nInjected-Header" not in response.content


# ===================================================================
# 6. Denylist at endpoint level (integration)
# ===================================================================

@pytest.mark.parametrize("scheme", sorted(DISALLOWED_REDIRECT_SCHEMES))
def test_e2e_denylist_rejected_through_endpoint(scheme: str) -> None:
    """Every denylist scheme is rejected through the full endpoint stack."""
    client = _endpoint_client()
    response = client.post(
        "/",
        json={"redirect_uris": [f"{scheme}://evil.example.com/x"]},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"
