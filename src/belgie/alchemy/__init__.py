"""Alchemy re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy.core import BelgieAdapter
    from belgie_alchemy.core.mixins import AccountMixin, CustomerMixin, IndividualMixin, OAuthStateMixin, SessionMixin
    from belgie_alchemy.organization.mixins import (
        OrganizationInvitationMixin,
        OrganizationMemberMixin,
        OrganizationMixin,
    )
    from belgie_alchemy.sso import SSOAdapter, SSODomainMixin, SSOProviderMixin
    from belgie_alchemy.stripe import StripeAdapter, StripeCustomerMixin, StripeSubscriptionMixin
    from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "AccountMixin",
    "BelgieAdapter",
    "CustomerMixin",
    "IndividualMixin",
    "OAuthStateMixin",
    "OrganizationInvitationMixin",
    "OrganizationMemberMixin",
    "OrganizationMixin",
    "SSOAdapter",
    "SSODomainMixin",
    "SSOProviderMixin",
    "SessionMixin",
    "StripeAdapter",
    "StripeCustomerMixin",
    "StripeSubscriptionMixin",
    "TeamMemberMixin",
    "TeamMixin",
]
