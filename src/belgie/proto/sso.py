"""SSO protocol re-exports for belgie consumers."""

from belgie_proto.sso import (
    OIDCClaimMapping,
    OIDCProviderConfig,
    SSOAdapterProtocol,
    SSODomainProtocol,
    SSOProviderProtocol,
)

__all__ = [
    "OIDCClaimMapping",
    "OIDCProviderConfig",
    "SSOAdapterProtocol",
    "SSODomainProtocol",
    "SSOProviderProtocol",
]
