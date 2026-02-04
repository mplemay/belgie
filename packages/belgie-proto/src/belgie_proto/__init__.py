"""Shared protocol interfaces for Belgie packages."""

from belgie_proto.account import AccountProtocol
from belgie_proto.adapter import AdapterProtocol
from belgie_proto.connection import DBConnection
from belgie_proto.oauth_access_token import OAuthAccessTokenProtocol
from belgie_proto.oauth_adapter import OAuthAdapterProtocol
from belgie_proto.oauth_authorization_code import OAuthAuthorizationCodeProtocol
from belgie_proto.oauth_client import OAuthClientProtocol
from belgie_proto.oauth_consent import OAuthConsentProtocol
from belgie_proto.oauth_refresh_token import OAuthRefreshTokenProtocol
from belgie_proto.oauth_state import OAuthStateProtocol
from belgie_proto.session import SessionProtocol
from belgie_proto.user import UserProtocol

__all__ = [
    "AccountProtocol",
    "AdapterProtocol",
    "DBConnection",
    "OAuthAccessTokenProtocol",
    "OAuthAdapterProtocol",
    "OAuthAuthorizationCodeProtocol",
    "OAuthClientProtocol",
    "OAuthConsentProtocol",
    "OAuthRefreshTokenProtocol",
    "OAuthStateProtocol",
    "SessionProtocol",
    "UserProtocol",
]
