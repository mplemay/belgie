"""Team protocol re-exports for belgie consumers."""

_PROTO_IMPORT_ERROR = "belgie.proto.team requires belgie-proto and the team types. Install with: uv add belgie-proto"

try:
    from belgie_proto.team import TeamAdapterProtocol, TeamMemberProtocol, TeamProtocol
except ModuleNotFoundError as exc:
    raise ImportError(_PROTO_IMPORT_ERROR) from exc

__all__ = [
    "TeamAdapterProtocol",
    "TeamMemberProtocol",
    "TeamProtocol",
]
