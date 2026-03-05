"""Alchemy re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy.core import BelgieAdapter
    from belgie_alchemy.core.mixins import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin
    from belgie_alchemy.organization.mixins import (
        OrganizationInvitationMixin,
        OrganizationMemberMixin,
        OrganizationMixin,
        OrganizationSessionMixin,
    )
    from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin, TeamSessionMixin
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "AccountMixin",
    "BelgieAdapter",
    "OAuthStateMixin",
    "OrganizationInvitationMixin",
    "OrganizationMemberMixin",
    "OrganizationMixin",
    "OrganizationSessionMixin",
    "SessionMixin",
    "TeamMemberMixin",
    "TeamMixin",
    "TeamSessionMixin",
    "UserMixin",
]
