import pytest

from auth_mcp.resource_server.token_validator import TokenInfo, TokenValidator

_VALID_TOKEN = "valid_token"  # noqa: S105
_EXPECTED_EXPIRES_AT = 9999999999
_EXPECTED_CUSTOM_EXPIRES_AT = 1700000000


class MockTokenValidator(TokenValidator):
    """Test implementation that validates a known token."""

    def __init__(self, valid_token: str = _VALID_TOKEN) -> None:
        self._valid_token = valid_token

    async def validate_token(
        self,
        token: str,
        resource: str | None = None,
    ) -> TokenInfo | None:
        if token == self._valid_token:
            return TokenInfo(
                subject="user@example.com",
                scopes=("read", "write"),
                expires_at=_EXPECTED_EXPIRES_AT,
                client_id="test_client",
                audience=resource,
            )
        return None


@pytest.mark.asyncio
async def test_mock_token_validator_valid_token() -> None:
    validator = MockTokenValidator()
    info = await validator.validate_token(_VALID_TOKEN, "https://mcp.example.com")
    assert info is not None
    assert info.subject == "user@example.com"
    assert info.scopes == ("read", "write")
    assert info.audience == "https://mcp.example.com"


@pytest.mark.asyncio
async def test_mock_token_validator_invalid_token() -> None:
    validator = MockTokenValidator()
    info = await validator.validate_token("invalid_token")
    assert info is None


def test_token_info_defaults() -> None:
    info = TokenInfo(subject="user@example.com")
    assert info.scopes == ()
    assert info.expires_at is None
    assert info.client_id is None
    assert info.audience is None


def test_token_info_all_fields() -> None:
    info = TokenInfo(
        subject="user@example.com",
        scopes=("read", "write"),
        expires_at=_EXPECTED_CUSTOM_EXPIRES_AT,
        client_id="client_abc",
        audience="https://mcp.example.com",
    )
    assert info.subject == "user@example.com"
    assert info.scopes == ("read", "write")
    assert info.expires_at == _EXPECTED_CUSTOM_EXPIRES_AT
