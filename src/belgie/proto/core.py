"""Core protocol re-exports for belgie consumers."""

_PROTO_IMPORT_ERROR = "belgie.proto.core requires belgie-proto. Install with: uv add belgie-proto"

try:
    from belgie_proto.core import (
        AccountAdapterProtocol,
        AccountProtocol,
        AccountType,
        AdapterProtocol,
        IndividualProtocol,
        OAuthAccountProtocol,
        OAuthStateProtocol,
        SessionProtocol,
    )
except ModuleNotFoundError as exc:
    raise ImportError(_PROTO_IMPORT_ERROR) from exc

__all__ = [
    "AccountAdapterProtocol",
    "AccountProtocol",
    "AccountType",
    "AdapterProtocol",
    "IndividualProtocol",
    "OAuthAccountProtocol",
    "OAuthStateProtocol",
    "SessionProtocol",
]
