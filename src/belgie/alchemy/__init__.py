"""Alchemy re-exports for belgie consumers."""

_ALCHEMY_IMPORT_ERROR = "belgie.alchemy requires the 'alchemy' extra. Install with: uv add belgie[alchemy]"

try:
    from belgie_alchemy.core.adapter import BelgieAdapter
    from belgie_alchemy.core.mixins import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin
    from belgie_alchemy.core.settings import DatabaseRuntimeProtocol, PostgresSettings, SqliteSettings
    from belgie_alchemy.organization.adapter import OrganizationAdapter
    from belgie_alchemy.organization.mixins import (
        OrganizationInvitationMixin,
        OrganizationMemberMixin,
        OrganizationMixin,
        OrganizationSessionMixin,
    )
    from belgie_alchemy.team.adapter import TeamAdapter
    from belgie_alchemy.team.mixins import TeamMemberMixin, TeamMixin, TeamSessionMixin
except ModuleNotFoundError as exc:
    raise ImportError(_ALCHEMY_IMPORT_ERROR) from exc

__all__ = [
    "AccountMixin",
    "BelgieAdapter",
    "DatabaseRuntimeProtocol",
    "OAuthStateMixin",
    "OrganizationAdapter",
    "OrganizationInvitationMixin",
    "OrganizationMemberMixin",
    "OrganizationMixin",
    "OrganizationSessionMixin",
    "PostgresSettings",
    "SessionMixin",
    "SqliteSettings",
    "TeamAdapter",
    "TeamMemberMixin",
    "TeamMixin",
    "TeamSessionMixin",
    "UserMixin",
]
