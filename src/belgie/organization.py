"""Organization re-exports for belgie consumers."""

_ORG_IMPORT_ERROR = "belgie.organization requires the 'organization' extra. Install with: uv add belgie[organization]"

try:
    from belgie_organization import (  # type: ignore[import-not-found]
        AcceptInvitationBody,
        AcceptInvitationView,
        CreateOrganizationBody,
        InvitationView,
        InviteMemberBody,
        MemberView,
        Organization,
        OrganizationClient,
        OrganizationFullView,
        OrganizationPlugin,
        OrganizationView,
        SetActiveOrganizationBody,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_ORG_IMPORT_ERROR) from exc

__all__ = [
    "AcceptInvitationBody",
    "AcceptInvitationView",
    "CreateOrganizationBody",
    "InvitationView",
    "InviteMemberBody",
    "MemberView",
    "Organization",
    "OrganizationClient",
    "OrganizationFullView",
    "OrganizationPlugin",
    "OrganizationView",
    "SetActiveOrganizationBody",
]
