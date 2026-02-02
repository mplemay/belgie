"""Shared protocol interfaces for Belgie packages."""

from belgie_proto.account import AccountProtocol
from belgie_proto.adapter import AdapterProtocol
from belgie_proto.connection import DBConnection
from belgie_proto.oauth_state import OAuthStateProtocol
from belgie_proto.session import SessionProtocol
from belgie_proto.user import UserProtocol

__all__ = [
    "AccountProtocol",
    "AdapterProtocol",
    "DBConnection",
    "OAuthStateProtocol",
    "SessionProtocol",
    "UserProtocol",
]
