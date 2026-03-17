from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict


class TokenInfo(BaseModel):
    """Information extracted from a validated access token."""

    model_config = ConfigDict(frozen=True)

    subject: str
    scopes: tuple[str, ...] = ()
    expires_at: int | None = None
    client_id: str | None = None
    audience: str | None = None


class TokenValidator(ABC):
    """Abstract token validator.

    Implementations can perform local validation (e.g. JWT signature verification)
    or remote validation (e.g. token introspection endpoint).

    Security considerations for implementors:

    - **Constant-time comparison**: When comparing tokens against stored values,
      use ``hmac.compare_digest()`` instead of ``==`` to prevent timing
      side-channel attacks. JWT libraries handle this internally.

    - **Caching**: Consider caching validated token results with an appropriate
      TTL to reduce load on the authorization server and improve latency.

    - **Rate limiting**: Consider rate limiting or circuit-breaking on repeated
      validation failures to mitigate brute-force and denial-of-service attacks
      against the authorization server.
    """

    @abstractmethod
    async def validate_token(self, token: str, resource: str | None = None) -> TokenInfo | None:
        """Validate a bearer token and return token info, or None if invalid."""
