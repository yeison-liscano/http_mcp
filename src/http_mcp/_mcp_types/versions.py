"""The protocol revision this server implements.

MCP split into two eras at revision ``2026-07-28``: earlier revisions negotiate a
session with an ``initialize`` handshake, while ``2026-07-28`` is stateless and
carries the protocol version, client identity, and client capabilities in every
request's ``_meta``. This server implements the stateless era only.
"""

LATEST_PROTOCOL_VERSION = "2026-07-28"

SUPPORTED_PROTOCOL_VERSIONS = (LATEST_PROTOCOL_VERSION,)
