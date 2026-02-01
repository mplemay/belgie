"""Shared protocol interfaces for Belgie packages."""

from proto.account import AccountProtocol
from proto.adapter import AdapterProtocol
from proto.oauth_state import OAuthStateProtocol
from proto.session import SessionProtocol
from proto.user import UserProtocol

__all__ = [
    "AccountProtocol",
    "AdapterProtocol",
    "OAuthStateProtocol",
    "SessionProtocol",
    "UserProtocol",
]
