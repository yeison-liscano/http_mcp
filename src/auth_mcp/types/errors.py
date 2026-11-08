import re

from pydantic import BaseModel, ConfigDict, field_validator

# Everything outside visible ASCII and space: CR, LF, NUL and the other C0 controls,
# DEL, C1 controls such as NEL, and non-ASCII characters such as U+2028. RFC 6750
# limits `error`, `error_description` and `scope` to visible ASCII anyway.
_UNSAFE_CHARS = re.compile(r"[^\x20-\x7e]")
# RFC 9110 section 5.6.2 token, which is what an auth-scheme is.
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def _sanitize_header_value(value: str) -> str:
    r"""Make a value safe inside an RFC 9110 quoted-string.

    Strips every character outside visible ASCII and space, then escapes backslash
    with \\ and double-quote with \".
    """
    value = _UNSAFE_CHARS.sub("", value)
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

    @field_validator("scheme")
    @classmethod
    def _validate_scheme(cls, v: str) -> str:
        # The scheme is emitted unquoted, so it cannot be sanitized like the parameters:
        # anything outside the token characters is refused instead.
        if not _TOKEN.fullmatch(v):
            msg = "scheme must be an RFC 9110 token"
            raise ValueError(msg)
        return v

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
