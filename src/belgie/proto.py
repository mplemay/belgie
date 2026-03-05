"""Protocol re-exports for belgie consumers."""

_PROTO_IMPORT_ERROR = "belgie.proto requires belgie-proto. Install with: uv add belgie-proto"

try:
    from belgie_proto.core.account import AccountProtocol
    from belgie_proto.core.adapter import AdapterProtocol
    from belgie_proto.core.database import DatabaseProtocol
    from belgie_proto.core.oauth_state import OAuthStateProtocol
    from belgie_proto.core.session import SessionProtocol
    from belgie_proto.core.user import UserProtocol
    from belgie_proto.organization.adapter import OrganizationAdapterProtocol
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.member import MemberProtocol
    from belgie_proto.organization.organization import OrganizationProtocol
    from belgie_proto.organization.session import OrganizationSessionProtocol
    from belgie_proto.team.adapter import TeamAdapterProtocol
    from belgie_proto.team.member import TeamMemberProtocol
    from belgie_proto.team.session import TeamSessionProtocol
    from belgie_proto.team.team import TeamProtocol
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
