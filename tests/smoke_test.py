import logging
import sys

LOGGER = logging.getLogger(__name__)


def main() -> int:
    """Run smoke tests on the installed package."""
    LOGGER.info("🧪 Starting smoke test...")

    # Test 1: Import main server class
    LOGGER.info("✓ Testing imports...")
    try:
        from http_mcp.server import MCPServer  # noqa: PLC0415
    except ImportError:
        LOGGER.exception("✗ Failed to import MCPServer")
        return 1

    # Test 2: Import types
    try:
        from http_mcp.types import Prompt, Tool  # noqa: PLC0415, F401
    except ImportError:
        LOGGER.exception("✗ Failed to import types")
        return 1

    # Test 3: Import exceptions
    try:
        from http_mcp.exceptions import (  # noqa: PLC0415, F401
            PromptNotFoundError,
            ToolNotFoundError,
        )
    except ImportError:
        LOGGER.exception("✗ Failed to import exceptions")
        return 1

    # Test 4: Create a basic server instance
    LOGGER.info("✓ Testing server instantiation...")
    try:
        server = MCPServer(
            name="test-server",
            version="0.0.1",
        )
        assert server.name == "test-server"
        assert server.version == "0.0.1"
        assert server.instructions is None
    except Exception:
        LOGGER.exception("✗ Failed to create server instance")
        return 1

    # Test 5: Verify capabilities
    LOGGER.info("✓ Testing capabilities...")
    try:
        capabilities = server.capabilities
        assert capabilities is not None
    except Exception:
        LOGGER.exception("✗ Failed to get capabilities")
        return 1

    LOGGER.info("✅ All smoke tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
