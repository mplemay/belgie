from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from belgie_proto.core import AdapterProtocol
from belgie_proto.core.account import AccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.core.user import UserProtocol
from belgie_proto.organization import OrganizationAdapterProtocol, OrganizationTeamAdapterProtocol
from belgie_proto.sso import SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol
from belgie_proto.team import TeamAdapterProtocol

from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.organization import OrganizationAdapter
from belgie_alchemy.sso import SSOAdapter
from belgie_alchemy.team import TeamAdapter


@dataclass
class ExampleUser:
    id: UUID
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str] = field(default_factory=list)
    custom_field: str | None = None


@dataclass
class ExampleAccount:
    id: UUID
    user_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    token_type: str | None
    scope: str | None
    id_token: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleSession:
    id: UUID
    user_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleOAuthState:
    id: UUID
    state: str
    code_verifier: str | None
    redirect_url: str | None
    created_at: datetime
    expires_at: datetime


@dataclass
class ExampleOrganization:
    id: UUID
    name: str
    slug: str
    logo: str | None
    organization_metadata: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleMember:
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleInvitation:
    id: UUID
    organization_id: UUID
    team_id: UUID | None
    email: str
    role: str
    status: str
    inviter_id: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleTeam:
    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleTeamMember:
    id: UUID
    team_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleSSOProvider:
    id: UUID
    organization_id: UUID
    provider_id: str
    issuer: str
    oidc_config: dict[str, str | list[str] | dict[str, str]]
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleSSODomain:
    id: UUID
    sso_provider_id: UUID
    domain: str
    verification_token: str
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


def test_user_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    user = ExampleUser(
        id=uuid4(),
        email="test@example.com",
        email_verified_at=now,
        name="Test User",
        image="https://example.com/image.jpg",
        created_at=now,
        updated_at=now,
        scopes=[],
        custom_field="custom value",
    )

    assert isinstance(user, UserProtocol)


def test_account_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    account = ExampleAccount(
        id=uuid4(),
        user_id=uuid4(),
        provider="google",
        provider_account_id="12345",
        access_token="token",
        refresh_token="refresh",
        expires_at=now,
        token_type="Bearer",
        scope="openid email",
        id_token="id_token",
        created_at=now,
        updated_at=now,
    )

    assert isinstance(account, AccountProtocol)


def test_session_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    session = ExampleSession(
        id=uuid4(),
        user_id=uuid4(),
        expires_at=now,
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0",
        created_at=now,
        updated_at=now,
    )

    assert isinstance(session, SessionProtocol)


def test_oauth_state_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    oauth_state = ExampleOAuthState(
        id=uuid4(),
        state="random_state",
        code_verifier="verifier",
        redirect_url="/dashboard",
        created_at=now,
        expires_at=now,
    )

    assert isinstance(oauth_state, OAuthStateProtocol)


def test_user_with_custom_fields_satisfies_protocol() -> None:
    now = datetime.now(UTC)
    user = ExampleUser(
        id=uuid4(),
        email="test@example.com",
        email_verified_at=None,
        name=None,
        image=None,
        created_at=now,
        updated_at=now,
        scopes=[],
        custom_field="this is a custom field not in the protocol",
    )

    assert isinstance(user, UserProtocol)


def test_sso_protocol_runtime_checks() -> None:
    now = datetime.now(UTC)
    provider = ExampleSSOProvider(
        id=uuid4(),
        organization_id=uuid4(),
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
            "claim_mapping": {"subject": "sub", "email": "email"},
            "scopes": ["openid", "email", "profile"],
        },
        created_at=now,
        updated_at=now,
    )
    domain = ExampleSSODomain(
        id=uuid4(),
        sso_provider_id=provider.id,
        domain="example.com",
        verification_token="token",
        verified_at=now,
        created_at=now,
        updated_at=now,
    )

    assert isinstance(provider, SSOProviderProtocol)
    assert isinstance(domain, SSODomainProtocol)


def test_alchemy_adapter_satisfies_adapter_protocol() -> None:
    """Verify BelgieAdapter implements AdapterProtocol using runtime checks."""

    adapter = BelgieAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
    )

    # Runtime protocol check - AdapterProtocol is now runtime_checkable
    assert isinstance(adapter, AdapterProtocol)

    # Verify all required methods are callable
    assert callable(adapter.create_user)
    assert callable(adapter.get_user_by_id)
    assert callable(adapter.get_user_by_email)
    assert callable(adapter.update_user)
    assert callable(adapter.create_account)
    assert callable(adapter.get_account)
    assert callable(adapter.get_account_by_user_and_provider)
    assert callable(adapter.update_account)
    assert callable(adapter.create_session)
    assert callable(adapter.get_session)
    assert callable(adapter.update_session)
    assert callable(adapter.delete_session)
    assert callable(adapter.delete_expired_sessions)
    assert callable(adapter.create_oauth_state)
    assert callable(adapter.get_oauth_state)
    assert callable(adapter.delete_oauth_state)
    assert callable(adapter.delete_user)


def test_organization_adapter_satisfies_organization_protocol_only() -> None:
    core_adapter = BelgieAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
    )
    organization_adapter = OrganizationAdapter(
        core=core_adapter,
        organization=ExampleOrganization,
        member=ExampleMember,
        invitation=ExampleInvitation,
    )

    assert isinstance(organization_adapter, OrganizationAdapterProtocol)
    assert not isinstance(organization_adapter, OrganizationTeamAdapterProtocol)
    assert not isinstance(organization_adapter, AdapterProtocol)
    assert callable(organization_adapter.create_organization)
    assert callable(organization_adapter.create_member)


def test_team_adapter_satisfies_team_protocol_only() -> None:
    core_adapter = BelgieAdapter(
        user=ExampleUser,
        account=ExampleAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
    )
    organization_adapter = OrganizationAdapter(
        core=core_adapter,
        organization=ExampleOrganization,
        member=ExampleMember,
        invitation=ExampleInvitation,
    )
    team_adapter = TeamAdapter(
        core=core_adapter,
        organization_adapter=organization_adapter,
        team=ExampleTeam,
        team_member=ExampleTeamMember,
    )

    assert isinstance(team_adapter, TeamAdapterProtocol)
    assert isinstance(team_adapter, OrganizationAdapterProtocol)
    assert isinstance(team_adapter, OrganizationTeamAdapterProtocol)
    assert not isinstance(team_adapter, AdapterProtocol)
    assert callable(team_adapter.create_organization)
    assert callable(team_adapter.create_team)


def test_sso_adapter_satisfies_protocol() -> None:
    adapter = SSOAdapter(
        sso_provider=ExampleSSOProvider,
        sso_domain=ExampleSSODomain,
    )

    assert isinstance(adapter, SSOAdapterProtocol)
    assert callable(adapter.create_provider)
    assert callable(adapter.get_provider_by_id)
    assert callable(adapter.get_provider_by_provider_id)
    assert callable(adapter.list_providers_for_organization)
    assert callable(adapter.update_provider)
    assert callable(adapter.delete_provider)
    assert callable(adapter.create_domain)
    assert callable(adapter.get_domain)
    assert callable(adapter.get_domain_by_name)
    assert callable(adapter.get_verified_domain)
    assert callable(adapter.list_domains_for_provider)
    assert callable(adapter.update_domain)
    assert callable(adapter.delete_domain)
    assert callable(adapter.delete_domains_for_provider)
