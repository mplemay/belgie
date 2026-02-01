from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl


class SimpleTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        pass  # This is where you would implement actual token validation


# Create MCPServer instance as a Resource Server
mcp = MCPServer(
    "Weather Service",
    # Token verifier for authentication
    token_verifier=SimpleTokenVerifier(),
    # Auth settings for RFC 9728 Protected Resource Metadata
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),  # Authorization Server URL
        resource_server_url=AnyHttpUrl("http://localhost:3001"),  # This server's URL
        required_scopes=["user"],
    ),
)
