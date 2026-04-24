"""Alchemy re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy.core import BelgieAdapter
    from belgie_alchemy.core.mixins import (
        AccountMixin,
        IndividualMixin,
        OAuthAccountMixin,
        OAuthStateMixin,
        SessionMixin,
    )
    from belgie_alchemy.oauth_server import (
        OAuthServerAccessTokenMixin,
        OAuthServerAdapter,
        OAuthServerAuthorizationCodeMixin,
        OAuthServerAuthorizationStateMixin,
        OAuthServerClientMixin,
        OAuthServerConsentMixin,
        OAuthServerRefreshTokenMixin,
    )
    from belgie_alchemy.organization.mixins import (
        OrganizationInvitationMixin,
        OrganizationMemberMixin,
        OrganizationMixin,
    )
    from belgie_alchemy.sso import SSOAdapter, SSOProviderMixin
    from belgie_alchemy.stripe import StripeAccountMixin, StripeAdapter, StripeSubscriptionMixin
    from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "AccountMixin",
    "BelgieAdapter",
    "IndividualMixin",
    "OAuthAccountMixin",
    "OAuthServerAccessTokenMixin",
    "OAuthServerAdapter",
    "OAuthServerAuthorizationCodeMixin",
    "OAuthServerAuthorizationStateMixin",
    "OAuthServerClientMixin",
    "OAuthServerConsentMixin",
    "OAuthServerRefreshTokenMixin",
    "OAuthStateMixin",
    "OrganizationInvitationMixin",
    "OrganizationMemberMixin",
    "OrganizationMixin",
    "SSOAdapter",
    "SSOProviderMixin",
    "SessionMixin",
    "StripeAccountMixin",
    "StripeAdapter",
    "StripeSubscriptionMixin",
    "TeamMemberMixin",
    "TeamMixin",
]
