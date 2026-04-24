"""SSO protocol re-exports for belgie consumers."""

from belgie_proto.sso import (
    DomainVerificationState,
    OIDCClaimMapping,
    OIDCProviderConfig,
    SSOAdapterProtocol,
    SSOProviderProtocol,
)

__all__ = [
    "DomainVerificationState",
    "OIDCClaimMapping",
    "OIDCProviderConfig",
    "SSOAdapterProtocol",
    "SSOProviderProtocol",
]
