from belgie_mcp.metadata import create_protected_resource_metadata_router
from belgie_mcp.verifier import BelgieMcpAuthBundle, BelgieOAuthTokenVerifier, build_belgie_oauth_auth


def hello() -> str:
    return "Hello from belgie-mcp!"


__all__ = [
    "BelgieMcpAuthBundle",
    "BelgieOAuthTokenVerifier",
    "build_belgie_oauth_auth",
    "create_protected_resource_metadata_router",
    "hello",
]
