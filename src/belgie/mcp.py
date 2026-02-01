"""MCP re-exports for belgie consumers."""

_MCP_IMPORT_ERROR = "belgie.mcp requires the 'mcp' extra. Install with: uv add belgie[mcp]"

try:
    from belgie_mcp import hello  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    raise ImportError(_MCP_IMPORT_ERROR) from exc

__all__ = [
    "hello",
]
