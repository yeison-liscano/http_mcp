from abc import ABC, abstractmethod

from auth_mcp.types.registration import ClientRegistrationRequest, ClientRegistrationResponse


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
    ) -> ClientRegistrationResponse:
        """Register a new client and return its registration details.

        Raises ``RegistrationError`` if the registration is rejected.
        """

    async def get_client(self, client_id: str) -> ClientRegistrationResponse | None:  # noqa: ARG002
        """Look up a previously registered client by ID.

        Returns ``None`` by default. Override for RFC 7592 client management.
        """
        return None
