"""Protocol re-exports for belgie consumers."""

_PROTO_IMPORT_ERROR = "belgie.proto requires belgie-proto. Install with: uv add belgie-proto"

try:
    from belgie_proto import (
        AccountProtocol,
        AdapterProtocol,
        DatabaseProtocol,
        InvitationProtocol,
        MemberProtocol,
        OAuthStateProtocol,
        OrganizationAdapterProtocol,
        OrganizationProtocol,
        OrganizationSessionProtocol,
        SessionProtocol,
        TeamAdapterProtocol,
        TeamMemberProtocol,
        TeamProtocol,
        TeamSessionProtocol,
        UserProtocol,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_PROTO_IMPORT_ERROR) from exc

__all__ = [
    "AccountProtocol",
    "AdapterProtocol",
    "DatabaseProtocol",
    "InvitationProtocol",
    "MemberProtocol",
    "OAuthStateProtocol",
    "OrganizationAdapterProtocol",
    "OrganizationProtocol",
    "OrganizationSessionProtocol",
    "SessionProtocol",
    "TeamAdapterProtocol",
    "TeamMemberProtocol",
    "TeamProtocol",
    "TeamSessionProtocol",
    "UserProtocol",
]
