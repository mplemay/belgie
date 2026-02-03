"""MCP re-exports for belgie consumers."""

_MCP_IMPORT_ERROR = "belgie.mcp requires the 'mcp' extra. Install with: uv add belgie[mcp]"

try:
    from belgie_mcp import (  # type: ignore[import-not-found]
        BelgieMcpAuthBundle,
        BelgieOAuthTokenVerifier,
        build_belgie_oauth_auth,
        hello,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_MCP_IMPORT_ERROR) from exc

__all__ = [
    "BelgieMcpAuthBundle",
    "BelgieOAuthTokenVerifier",
    "build_belgie_oauth_auth",
    "hello",
]
