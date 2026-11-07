from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from auth_mcp.types.registration import ClientRegistrationRequest, ClientRegistrationResponse


@dataclass(frozen=True)
class RegistrationRejected:
    """The store refused a registration. `reason` is sent to the client."""

    reason: str
    type: Literal["registration_rejected"] = "registration_rejected"


class ClientStore(ABC):
    """Abstract client store for Dynamic Client Registration (RFC 7591).

    Implementations must persist registered clients and return valid
    ``ClientRegistrationResponse`` instances.

    Security considerations for implementors:

    - **Client IDs**: Generate cryptographically random client IDs
      (e.g. ``secrets.token_urlsafe(32)``) to prevent enumeration attacks.

    - **Client secrets**: If issuing client secrets, store only hashed values
      (e.g. using ``hashlib.scrypt`` or ``bcrypt``). Never store secrets in
      plaintext.

    - **Rate limiting**: Enforce rate limits on the registration endpoint to
      prevent abuse and resource exhaustion from automated registrations.
    """

    @abstractmethod
    async def register_client(
        self,
        request: ClientRegistrationRequest,
    ) -> ClientRegistrationResponse | RegistrationRejected:
        """Register a new client, or return ``RegistrationRejected`` to refuse it."""

    async def get_client(self, client_id: str) -> ClientRegistrationResponse | None:  # noqa: ARG002
        """Look up a previously registered client by ID.

        Returns ``None`` by default. Override for RFC 7592 client management.
        """
        return None
