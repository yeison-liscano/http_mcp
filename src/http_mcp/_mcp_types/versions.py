"""Protocol revisions this server implements.

MCP split into two eras at revision ``2026-07-28``. *Legacy* revisions negotiate a
session with an ``initialize`` handshake; *modern* revisions are stateless and carry
the protocol version, client identity, and client capabilities in every request's
``_meta``. This server is dual-era: it serves both, choosing per request.
"""

LATEST_PROTOCOL_VERSION = "2026-07-28"

MODERN_PROTOCOL_VERSIONS = ("2026-07-28",)

LEGACY_PROTOCOL_VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")

# Newest first: clients pick the first mutually supported entry.
SUPPORTED_PROTOCOL_VERSIONS = (
    *reversed(MODERN_PROTOCOL_VERSIONS),
    *reversed(LEGACY_PROTOCOL_VERSIONS),
)
