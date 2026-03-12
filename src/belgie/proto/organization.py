"""Organization protocol re-exports for belgie consumers."""

_PROTO_IMPORT_ERROR = (
    "belgie.proto.organization requires belgie-proto and the organization types. Install with: uv add belgie-proto"
)

try:
    from belgie_proto.organization import (
        InvitationProtocol,
        MemberProtocol,
        OrganizationAdapterProtocol,
        OrganizationProtocol,
        OrganizationSessionProtocol,
        OrganizationTeamAdapterProtocol,
        PendingInvitationConflictError,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_PROTO_IMPORT_ERROR) from exc

__all__ = [
    "InvitationProtocol",
    "MemberProtocol",
    "OrganizationAdapterProtocol",
    "OrganizationProtocol",
    "OrganizationSessionProtocol",
    "OrganizationTeamAdapterProtocol",
    "PendingInvitationConflictError",
]
