"""Mixin re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy.mixins requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy.core.mixins import (
        AccountMixin,
        IndividualMixin,
        OAuthAccountMixin,
        OAuthStateMixin,
        SessionMixin,
    )
    from belgie_alchemy.organization.mixins import (
        OrganizationInvitationMixin,
        OrganizationMemberMixin,
        OrganizationMixin,
    )
    from belgie_alchemy.stripe import StripeAccountMixin, StripeSubscriptionMixin
    from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "AccountMixin",
    "IndividualMixin",
    "OAuthAccountMixin",
    "OAuthStateMixin",
    "OrganizationInvitationMixin",
    "OrganizationMemberMixin",
    "OrganizationMixin",
    "SessionMixin",
    "StripeAccountMixin",
    "StripeSubscriptionMixin",
    "TeamMemberMixin",
    "TeamMixin",
]
