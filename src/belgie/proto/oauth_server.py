"""OAuth server protocol re-exports for belgie consumers."""

from belgie_proto.oauth_server import (
    AuthorizationIntent,
    OAuthAccessTokenProtocol,
    OAuthAudience,
    OAuthAuthorizationCodeProtocol,
    OAuthAuthorizationStateProtocol,
    OAuthClientProtocol,
    OAuthClientType,
    OAuthConsentProtocol,
    OAuthRefreshTokenProtocol,
    OAuthServerAdapterProtocol,
    OAuthSubjectType,
    TokenEndpointAuthMethod,
)

__all__ = [
    "AuthorizationIntent",
    "OAuthAccessTokenProtocol",
    "OAuthAudience",
    "OAuthAuthorizationCodeProtocol",
    "OAuthAuthorizationStateProtocol",
    "OAuthClientProtocol",
    "OAuthClientType",
    "OAuthConsentProtocol",
    "OAuthRefreshTokenProtocol",
    "OAuthServerAdapterProtocol",
    "OAuthSubjectType",
    "TokenEndpointAuthMethod",
]
