from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from belgie_proto.core import AdapterProtocol
from belgie_proto.core.account import AccountProtocol, AccountType
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.oauth_account import OAuthAccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.oauth_server import (
    OAuthServerAccessTokenProtocol,
    OAuthServerAdapterProtocol,
    OAuthServerAuthorizationCodeProtocol,
    OAuthServerAuthorizationStateProtocol,
    OAuthServerClientProtocol,
    OAuthServerConsentProtocol,
    OAuthServerRefreshTokenProtocol,
)
from belgie_proto.organization import (
    OrganizationAdapterProtocol,
    OrganizationProtocol,
    OrganizationTeamAdapterProtocol,
)
from belgie_proto.sso import SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol
from belgie_proto.stripe import (
    StripeAccountProtocol,
    StripeAdapterProtocol,
    StripeBillingInterval,
    StripeSubscriptionProtocol,
)
from belgie_proto.team import TeamAdapterProtocol, TeamProtocol

from belgie_alchemy.__tests__.fixtures.core.models import (
    OAuthServerAccessToken,
    OAuthServerAuthorizationCode,
    OAuthServerAuthorizationState,
    OAuthServerClient,
    OAuthServerConsent,
    OAuthServerRefreshToken,
)
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.oauth_server import OAuthServerAdapter
from belgie_alchemy.organization import OrganizationAdapter
from belgie_alchemy.sso import SSOAdapter
from belgie_alchemy.stripe import StripeAdapter
from belgie_alchemy.team import TeamAdapter


@dataclass
class ExampleAccount:
    id: UUID
    account_type: AccountType
    name: str | None
    created_at: datetime
    updated_at: datetime
    custom_field: str | None = None


@dataclass
class ExampleIndividual:
    id: UUID
    account_type: AccountType
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str] = field(default_factory=list)
    custom_field: str | None = None


@dataclass
class ExampleOAuthAccount:
    id: UUID
    individual_id: UUID
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
    individual_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleOAuthState:
    id: UUID
    state: str
    provider: str | None
    individual_id: UUID | None
    code_verifier: str | None
    nonce: str | None
    intent: str
    redirect_url: str | None
    error_redirect_url: str | None
    new_user_redirect_url: str | None
    payload: object | None
    request_sign_up: bool
    created_at: datetime
    expires_at: datetime


@dataclass
class ExampleOrganization:
    id: UUID
    account_type: AccountType
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleMember:
    id: UUID
    organization_id: UUID
    individual_id: UUID
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
    inviter_individual_id: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleTeam:
    id: UUID
    account_type: AccountType
    organization_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleTeamMember:
    id: UUID
    team_id: UUID
    individual_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleStripeIndividual:
    id: UUID
    account_type: AccountType
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str]
    stripe_customer_id: str | None


@dataclass
class ExampleStripeAccountOrganization:
    id: UUID
    account_type: AccountType
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime
    stripe_customer_id: str | None


@dataclass
class ExampleStripeSubscription:
    id: UUID
    plan: str
    account_id: UUID
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    status: str
    period_start: datetime | None
    period_end: datetime | None
    cancel_at_period_end: bool
    cancel_at: datetime | None
    canceled_at: datetime | None
    ended_at: datetime | None
    billing_interval: StripeBillingInterval | None
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


@dataclass
class ExampleOAuthClient:
    id: UUID
    client_id: str
    client_secret: str | None
    client_secret_hash: str | None
    disabled: bool | None
    skip_consent: bool | None
    redirect_uris: list[str] | None
    post_logout_redirect_uris: list[str] | None
    token_endpoint_auth_method: str
    grant_types: list[str]
    response_types: list[str]
    scope: str | None
    client_name: str | None
    client_uri: str | None
    logo_uri: str | None
    contacts: list[str] | None
    tos_uri: str | None
    policy_uri: str | None
    software_id: str | None
    software_version: str | None
    software_statement: str | None
    type: str | None
    subject_type: str | None
    require_pkce: bool | None
    enable_end_session: bool | None
    reference_id: str | None
    metadata_json: dict[str, str] | dict[str, object] | None
    client_id_issued_at: int | None
    client_secret_expires_at: int | None
    individual_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ExampleOAuthAuthorizationState:
    id: UUID
    state: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str | None
    resource: str | None
    scopes: list[str] | None
    nonce: str | None
    prompt: str | None
    intent: str
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


@dataclass
class ExampleOAuthAuthorizationCode:
    id: UUID
    code_hash: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str | None
    scopes: list[str]
    resource: str | None
    nonce: str | None
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    expires_at: datetime


@dataclass
class ExampleOAuthAccessToken:
    id: UUID
    token_hash: str
    client_id: str
    scopes: list[str]
    resource: str | list[str] | None
    refresh_token_id: UUID | None
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    expires_at: datetime


@dataclass
class ExampleOAuthRefreshToken:
    id: UUID
    token_hash: str
    client_id: str
    scopes: list[str]
    resource: str | None
    individual_id: UUID | None
    session_id: UUID | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass
class ExampleOAuthConsent:
    id: UUID
    client_id: str
    individual_id: UUID
    reference_id: str | None
    scopes: list[str]
    created_at: datetime
    updated_at: datetime


def test_customer_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    account = ExampleAccount(
        id=uuid4(),
        account_type=AccountType.INDIVIDUAL,
        name="Test Account",
        created_at=now,
        updated_at=now,
        custom_field="custom value",
    )

    assert isinstance(account, AccountProtocol)


def test_individual_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    individual = ExampleIndividual(
        id=uuid4(),
        account_type=AccountType.INDIVIDUAL,
        email="test@example.com",
        email_verified_at=now,
        name="Test Individual",
        image="https://example.com/image.jpg",
        created_at=now,
        updated_at=now,
        scopes=[],
        custom_field="custom value",
    )

    assert isinstance(individual, IndividualProtocol)


def test_account_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    account = ExampleOAuthAccount(
        id=uuid4(),
        individual_id=uuid4(),
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

    assert isinstance(account, OAuthAccountProtocol)


def test_session_protocol_runtime_check() -> None:
    now = datetime.now(UTC)
    session = ExampleSession(
        id=uuid4(),
        individual_id=uuid4(),
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
        provider="google",
        individual_id=uuid4(),
        code_verifier="verifier",
        nonce="nonce",
        intent="signin",
        redirect_url="/dashboard",
        error_redirect_url="/error",
        new_user_redirect_url="/welcome",
        payload={"source": "test"},
        request_sign_up=True,
        created_at=now,
        expires_at=now,
    )

    assert isinstance(oauth_state, OAuthStateProtocol)


def test_organization_and_team_protocol_runtime_checks() -> None:
    now = datetime.now(UTC)
    organization = ExampleOrganization(
        id=uuid4(),
        account_type=AccountType.ORGANIZATION,
        name="Acme",
        slug="acme",
        logo=None,
        created_at=now,
        updated_at=now,
    )
    team = ExampleTeam(
        id=uuid4(),
        account_type=AccountType.TEAM,
        organization_id=organization.id,
        name="Platform",
        created_at=now,
        updated_at=now,
    )

    assert isinstance(organization, OrganizationProtocol)
    assert isinstance(team, TeamProtocol)


def test_individual_with_custom_fields_satisfies_protocol() -> None:
    now = datetime.now(UTC)
    individual = ExampleIndividual(
        id=uuid4(),
        account_type=AccountType.INDIVIDUAL,
        email="test@example.com",
        email_verified_at=None,
        name=None,
        image=None,
        created_at=now,
        updated_at=now,
        scopes=[],
        custom_field="this field is not in the protocol",
    )

    assert isinstance(individual, IndividualProtocol)


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


def test_stripe_protocol_runtime_checks() -> None:
    now = datetime.now(UTC)
    individual = ExampleStripeIndividual(
        id=uuid4(),
        account_type=AccountType.INDIVIDUAL,
        email="stripe-individual@example.com",
        email_verified_at=None,
        name=None,
        image=None,
        created_at=now,
        updated_at=now,
        scopes=[],
        stripe_customer_id="cus_123",
    )
    organization = ExampleStripeAccountOrganization(
        id=uuid4(),
        account_type=AccountType.ORGANIZATION,
        name="Acme",
        slug="acme",
        logo=None,
        created_at=now,
        updated_at=now,
        stripe_customer_id="cus_org_123",
    )
    subscription = ExampleStripeSubscription(
        id=uuid4(),
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        status="active",
        period_start=now,
        period_end=now,
        cancel_at_period_end=False,
        cancel_at=None,
        canceled_at=None,
        ended_at=None,
        billing_interval="month",
        created_at=now,
        updated_at=now,
    )

    assert isinstance(individual, StripeAccountProtocol)
    assert isinstance(organization, StripeAccountProtocol)
    assert isinstance(subscription, StripeSubscriptionProtocol)


def test_alchemy_adapter_satisfies_adapter_protocol() -> None:
    adapter = BelgieAdapter(
        account=ExampleAccount,
        individual=ExampleIndividual,
        oauth_account=ExampleOAuthAccount,
        session=ExampleSession,
        oauth_state=ExampleOAuthState,
    )

    assert isinstance(adapter, AdapterProtocol)
    assert callable(adapter.get_account_by_id)
    assert callable(adapter.update_account)
    assert callable(adapter.create_individual)
    assert callable(adapter.get_individual_by_id)
    assert callable(adapter.get_individual_by_email)
    assert callable(adapter.update_individual)
    assert callable(adapter.create_oauth_account)
    assert callable(adapter.get_oauth_account)
    assert callable(adapter.get_oauth_account_by_id)
    assert callable(adapter.get_oauth_account_by_individual_and_provider)
    assert callable(adapter.get_oauth_account_by_individual_provider_account_id)
    assert callable(adapter.list_oauth_accounts)
    assert callable(adapter.update_oauth_account)
    assert callable(adapter.update_oauth_account_by_id)
    assert callable(adapter.delete_oauth_account)
    assert callable(adapter.create_session)
    assert callable(adapter.get_session)
    assert callable(adapter.update_session)
    assert callable(adapter.delete_session)
    assert callable(adapter.delete_expired_sessions)
    assert callable(adapter.create_oauth_state)
    assert callable(adapter.get_oauth_state)
    assert callable(adapter.delete_oauth_state)
    assert callable(adapter.delete_individual)


def test_organization_adapter_satisfies_organization_protocol_only() -> None:
    organization_adapter = OrganizationAdapter(
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
    team_adapter = TeamAdapter(
        organization=ExampleOrganization,
        member=ExampleMember,
        invitation=ExampleInvitation,
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


def test_stripe_adapter_satisfies_protocol() -> None:
    adapter = StripeAdapter(subscription=ExampleStripeSubscription)

    assert isinstance(adapter, StripeAdapterProtocol)
    assert callable(adapter.create_subscription)
    assert callable(adapter.get_subscription_by_id)
    assert callable(adapter.get_subscription_by_stripe_subscription_id)
    assert callable(adapter.list_subscriptions)
    assert callable(adapter.get_active_subscription)
    assert callable(adapter.get_incomplete_subscription)
    assert callable(adapter.update_subscription)


def test_oauth_entity_protocol_runtime_checks() -> None:
    now = datetime.now(UTC)
    individual_id = uuid4()
    session_id = uuid4()
    refresh_token_id = uuid4()
    client = ExampleOAuthClient(
        id=uuid4(),
        client_id="client-123",
        client_secret="secret-value",
        client_secret_hash="secret-hash",
        disabled=False,
        skip_consent=False,
        redirect_uris=["https://client.example/callback"],
        post_logout_redirect_uris=["https://client.example/logout"],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="openid profile",
        client_name="Example Client",
        client_uri="https://client.example",
        logo_uri="https://client.example/logo.png",
        contacts=["ops@client.example"],
        tos_uri="https://client.example/tos",
        policy_uri="https://client.example/policy",
        software_id="software-id",
        software_version="1.0.0",
        software_statement="software-statement",
        type="web",
        subject_type="pairwise",
        require_pkce=True,
        enable_end_session=True,
        reference_id=None,
        metadata_json=None,
        client_id_issued_at=123,
        client_secret_expires_at=0,
        individual_id=None,
        created_at=now,
        updated_at=now,
    )
    authorization_state = ExampleOAuthAuthorizationState(
        id=uuid4(),
        state="state-123",
        client_id=client.client_id,
        redirect_uri="https://client.example/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge",
        resource="https://api.example",
        scopes=["openid"],
        nonce="nonce-123",
        prompt="login",
        intent="login",
        individual_id=individual_id,
        session_id=session_id,
        created_at=now,
        updated_at=now,
        expires_at=now,
    )
    authorization_code = ExampleOAuthAuthorizationCode(
        id=uuid4(),
        code_hash="code-hash",
        client_id=client.client_id,
        redirect_uri="https://client.example/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge",
        scopes=["openid"],
        resource="https://api.example",
        nonce="nonce-123",
        individual_id=individual_id,
        session_id=session_id,
        created_at=now,
        expires_at=now,
    )
    access_token = ExampleOAuthAccessToken(
        id=uuid4(),
        token_hash="access-hash",
        client_id=client.client_id,
        scopes=["openid"],
        resource=["https://api.example", "https://userinfo.example"],
        refresh_token_id=refresh_token_id,
        individual_id=individual_id,
        session_id=session_id,
        created_at=now,
        expires_at=now,
    )
    refresh_token = ExampleOAuthRefreshToken(
        id=refresh_token_id,
        token_hash="refresh-hash",
        client_id=client.client_id,
        scopes=["openid", "offline_access"],
        resource="https://api.example",
        individual_id=individual_id,
        session_id=session_id,
        created_at=now,
        updated_at=now,
        expires_at=now,
        revoked_at=None,
    )
    consent = ExampleOAuthConsent(
        id=uuid4(),
        client_id=client.client_id,
        individual_id=individual_id,
        reference_id=None,
        scopes=["openid", "profile"],
        created_at=now,
        updated_at=now,
    )

    assert isinstance(client, OAuthServerClientProtocol)
    assert isinstance(authorization_state, OAuthServerAuthorizationStateProtocol)
    assert isinstance(authorization_code, OAuthServerAuthorizationCodeProtocol)
    assert isinstance(access_token, OAuthServerAccessTokenProtocol)
    assert isinstance(refresh_token, OAuthServerRefreshTokenProtocol)
    assert isinstance(consent, OAuthServerConsentProtocol)


def test_oauth_server_adapter_satisfies_protocol() -> None:
    adapter = OAuthServerAdapter(
        oauth_client=OAuthServerClient,
        oauth_authorization_state=OAuthServerAuthorizationState,
        oauth_authorization_code=OAuthServerAuthorizationCode,
        oauth_access_token=OAuthServerAccessToken,
        oauth_refresh_token=OAuthServerRefreshToken,
        oauth_consent=OAuthServerConsent,
    )

    assert isinstance(adapter, OAuthServerAdapterProtocol)
