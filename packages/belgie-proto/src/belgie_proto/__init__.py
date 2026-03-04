"""Shared protocol interfaces for Belgie packages."""

from belgie_proto.account import AccountProtocol
from belgie_proto.adapter import AdapterProtocol
from belgie_proto.connection import DBConnection
from belgie_proto.database import DatabaseProtocol
from belgie_proto.invitation import InvitationProtocol
from belgie_proto.member import MemberProtocol
from belgie_proto.oauth_state import OAuthStateProtocol
from belgie_proto.organization import OrganizationProtocol
from belgie_proto.organization_adapter import OrganizationAdapterProtocol, TeamAdapterProtocol
from belgie_proto.organization_session import OrganizationSessionProtocol, TeamSessionProtocol
from belgie_proto.session import SessionProtocol
from belgie_proto.team import TeamProtocol
from belgie_proto.team_member import TeamMemberProtocol
from belgie_proto.user import UserProtocol

__all__ = [
    "AccountProtocol",
    "AdapterProtocol",
    "DBConnection",
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
