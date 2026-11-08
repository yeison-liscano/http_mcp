import pytest

from auth_mcp.authorization_server.client_store import ClientStore, RegistrationRejected
from auth_mcp.types.registration import ClientRegistrationRequest, ClientRegistrationResponse


class MockClientStore(ClientStore):
    def __init__(self) -> None:
        self._counter = 0
        self._clients: dict[str, ClientRegistrationResponse] = {}

    async def register_client(
        self,
        request: ClientRegistrationRequest,
    ) -> ClientRegistrationResponse:
        self._counter += 1
        client_id = f"client_{self._counter}"
        response = ClientRegistrationResponse(
            client_id=client_id,
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            response_types=request.response_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
        )
        self._clients[client_id] = response
        return response

    async def get_client(self, client_id: str) -> ClientRegistrationResponse | None:
        return self._clients.get(client_id)


class RejectingClientStore(ClientStore):
    async def register_client(
        self,
        request: ClientRegistrationRequest,  # noqa: ARG002
    ) -> RegistrationRejected:
        return RegistrationRejected("Registration denied")


@pytest.mark.asyncio
async def test_register_client_returns_valid_response() -> None:
    store = MockClientStore()
    request = ClientRegistrationRequest(
        redirect_uris=("https://example.com/callback",),
    )
    response = await store.register_client(request)
    assert response.client_id == "client_1"
    assert response.redirect_uris == ("https://example.com/callback",)
    assert response.grant_types == ("authorization_code",)
    assert response.token_endpoint_auth_method == "none"  # noqa: S105


@pytest.mark.asyncio
async def test_default_get_client_returns_none() -> None:
    store = RejectingClientStore()
    result = await store.get_client("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_overridden_get_client_returns_stored_client() -> None:
    store = MockClientStore()
    request = ClientRegistrationRequest(
        redirect_uris=("https://example.com/callback",),
    )
    registered = await store.register_client(request)
    result = await store.get_client(registered.client_id)
    assert result is not None
    assert result.client_id == registered.client_id


@pytest.mark.asyncio
async def test_register_client_returns_the_rejection() -> None:
    store = RejectingClientStore()
    request = ClientRegistrationRequest(
        redirect_uris=("https://example.com/callback",),
    )
    assert await store.register_client(request) == RegistrationRejected("Registration denied")
