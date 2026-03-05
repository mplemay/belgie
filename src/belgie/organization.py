"""Organization re-exports for belgie consumers."""

_ORG_IMPORT_ERROR = "belgie.organization requires the 'organization' extra. Install with: uv add belgie[organization]"

try:
    from belgie_organization import (  # type: ignore[import-not-found]
        InvitationView,
        MemberView,
        Organization,
        OrganizationClient,
        OrganizationFullView,
        OrganizationPlugin,
        OrganizationView,
        RoleValue,
        has_any_role,
        has_role,
        normalize_roles,
        parse_roles,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_ORG_IMPORT_ERROR) from exc

__all__ = [
    "InvitationView",
    "MemberView",
    "Organization",
    "OrganizationClient",
    "OrganizationFullView",
    "OrganizationPlugin",
    "OrganizationView",
    "RoleValue",
    "has_any_role",
    "has_role",
    "normalize_roles",
    "parse_roles",
]
