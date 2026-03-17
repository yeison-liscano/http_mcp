import re

from pydantic import BaseModel, ConfigDict

_CRLF_CHARS = re.compile(r"[\r\n]")


def _sanitize_header_value(value: str) -> str:
    r"""Escape characters that are unsafe inside RFC 7230 quoted-string values.

    Strips CR/LF, then escapes backslash with \\ and double-quote with \".
    """
    value = _CRLF_CHARS.sub("", value)
    return value.replace("\\", "\\\\").replace('"', '\\"')


class OAuthErrorResponse(BaseModel):
    """OAuth 2.1 error response (RFC 6749 Section 5.2)."""

    model_config = ConfigDict(frozen=True)

    error: str
    error_description: str | None = None
    error_uri: str | None = None


class WWWAuthenticateChallenge(BaseModel):
    """Structured representation of a WWW-Authenticate header value."""

    model_config = ConfigDict(frozen=True)

    scheme: str = "Bearer"
    realm: str | None = None
    resource_metadata: str | None = None
    scope: str | None = None
    error: str | None = None
    error_description: str | None = None

    def to_header_value(self) -> str:
        """Build the WWW-Authenticate header string.

        All parameter values are sanitized to prevent header injection
        per RFC 7230 quoted-string rules.
        """
        params: list[str] = []
        if self.realm is not None:
            params.append(f'realm="{_sanitize_header_value(self.realm)}"')
        if self.resource_metadata is not None:
            params.append(f'resource_metadata="{_sanitize_header_value(self.resource_metadata)}"')
        if self.scope is not None:
            params.append(f'scope="{_sanitize_header_value(self.scope)}"')
        if self.error is not None:
            params.append(f'error="{_sanitize_header_value(self.error)}"')
        if self.error_description is not None:
            params.append(
                f'error_description="{_sanitize_header_value(self.error_description)}"',
            )
        if params:
            return f"{self.scheme} {', '.join(params)}"
        return self.scheme
