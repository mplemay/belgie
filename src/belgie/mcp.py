"""MCP re-exports for belgie consumers."""

_MCP_IMPORT_ERROR = "belgie.mcp requires the 'mcp' extra. Install with: uv add belgie[mcp]"

try:
    from belgie_mcp import (  # type: ignore[import-not-found]
        BelgieMcpPlugin,
        BelgieOAuthTokenVerifier,
        create_protected_resource_metadata_router,
        mcp_auth,
        mcp_token_verifier,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_MCP_IMPORT_ERROR) from exc

__all__ = [
    "BelgieMcpPlugin",
    "BelgieOAuthTokenVerifier",
    "create_protected_resource_metadata_router",
    "mcp_auth",
    "mcp_token_verifier",
]
