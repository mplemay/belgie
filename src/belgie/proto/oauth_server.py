"""OAuth server protocol re-exports for belgie consumers."""

from belgie_proto.oauth_server import (
    AuthorizationIntent,
    OAuthServerAccessTokenProtocol,
    OAuthServerAdapterProtocol,
    OAuthServerAudience,
    OAuthServerAuthorizationCodeProtocol,
    OAuthServerAuthorizationStateProtocol,
    OAuthServerClientProtocol,
    OAuthServerClientType,
    OAuthServerConsentProtocol,
    OAuthServerRefreshTokenProtocol,
    OAuthServerSubjectType,
    TokenEndpointAuthMethod,
)

__all__ = [
    "AuthorizationIntent",
    "OAuthServerAccessTokenProtocol",
    "OAuthServerAdapterProtocol",
    "OAuthServerAudience",
    "OAuthServerAuthorizationCodeProtocol",
    "OAuthServerAuthorizationStateProtocol",
    "OAuthServerClientProtocol",
    "OAuthServerClientType",
    "OAuthServerConsentProtocol",
    "OAuthServerRefreshTokenProtocol",
    "OAuthServerSubjectType",
    "TokenEndpointAuthMethod",
]
