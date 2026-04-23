# ruff: noqa: ARG002, ARG005, E501, EM101, TRY003

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from belgie_core.core.plugin import AuthenticatedProfile
from belgie_core.core.settings import BelgieSettings
from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo
from belgie_sso.plugin import SSOPlugin
from belgie_sso.saml import SAMLResponseProfile, SAMLStartResult
from belgie_sso.settings import EnterpriseSSO
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


@dataclass
class FakeProvider:
    id: UUID
    organization_id: UUID | None
    created_by_individual_id: UUID | None
    provider_type: str
    provider_id: str
    issuer: str
    oidc_config: dict[str, str | bool | list[str] | dict[str, str]] | None
    saml_config: dict[str, str | bool | list[str] | dict[str, str]] | None
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeDomain:
    id: UUID
    sso_provider_id: UUID
    domain: str
    verification_token: str
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeIndividual:
    id: UUID
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str]


class DummyBelgie:
    def __init__(self, client: object) -> None:
        self._client = client
        self.plugins: list[object] = []
        self.settings = SimpleNamespace(
            base_url="http://localhost:8000",
            urls=SimpleNamespace(signin_redirect="/dashboard"),
        )

    async def __call__(self) -> object:
        return self._client

    async def after_authenticate(
        self,
        *,
        client: object,
        request: object,
        individual: object,
        profile: object,
    ) -> None:
        return None


class FakeSSOAdapter:
    def __init__(self, providers: list[FakeProvider], domains: list[FakeDomain]) -> None:
        self.providers = {provider.provider_id: provider for provider in providers}
        self.providers_by_id = {provider.id: provider for provider in providers}
        self.domains = list(domains)

    async def create_provider(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError

    async def get_provider_by_provider_id(self, _db: object, *, provider_id: str) -> FakeProvider | None:
        return self.providers.get(provider_id)

    async def get_provider_by_id(self, _db: object, *, sso_provider_id: UUID) -> FakeProvider | None:
        return self.providers_by_id.get(sso_provider_id)

    async def list_domains_for_provider(self, _db: object, *, sso_provider_id: UUID) -> list[FakeDomain]:
        return [domain for domain in self.domains if domain.sso_provider_id == sso_provider_id]

    async def get_verified_domain(self, _db: object, *, domain: str) -> FakeDomain | None:
        return next(
            (item for item in self.domains if item.domain == domain and item.verified_at is not None),
            None,
        )

    async def list_verified_domains_matching(self, _db: object, *, domain: str) -> list[FakeDomain]:
        return [
            item
            for item in self.domains
            if item.verified_at is not None and (item.domain == domain or domain.endswith(f".{item.domain}"))
        ]

    async def list_providers_for_organization(self, _db: object, *, organization_id: UUID) -> list[FakeProvider]:
        return [provider for provider in self.providers.values() if provider.organization_id == organization_id]

    async def list_providers_for_individual(self, _db: object, *, individual_id: UUID) -> list[FakeProvider]:
        return [provider for provider in self.providers.values() if provider.created_by_individual_id == individual_id]

    async def update_provider(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError

    async def delete_provider(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError

    async def create_domain(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError

    async def get_domain(self, _db: object, *, domain_id: UUID) -> FakeDomain | None:
        return next((domain for domain in self.domains if domain.id == domain_id), None)

    async def get_domain_by_name(self, _db: object, *, domain: str) -> FakeDomain | None:
        return next((item for item in self.domains if item.domain == domain), None)

    async def update_domain(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError

    async def delete_domain(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError

    async def delete_domains_for_provider(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise NotImplementedError


class FakeOrganizationAdapter:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.created_members: list[tuple[UUID, UUID, str]] = []

    async def get_organization_by_id(self, _db: object, organization_id: UUID) -> object | None:
        if organization_id == self.organization_id:
            return object()
        return None

    async def get_organization_by_slug(self, _db: object, slug: str) -> object | None:
        if slug == "acme":
            return SimpleNamespace(id=self.organization_id)
        return None

    async def get_member(self, _db: object, *, organization_id: UUID, individual_id: UUID) -> object | None:
        return next(
            (
                object()
                for existing_organization_id, existing_individual_id, _role in self.created_members
                if existing_organization_id == organization_id and existing_individual_id == individual_id
            ),
            None,
        )

    async def create_member(self, _db: object, *, organization_id: UUID, individual_id: UUID, role: str) -> object:
        self.created_members.append((organization_id, individual_id, role))
        return object()


class FakeAdapter:
    def __init__(self) -> None:
        self.oauth_states: dict[str, SimpleNamespace] = {}
        self.individuals_by_email: dict[str, FakeIndividual] = {}
        self.individuals_by_id: dict[UUID, FakeIndividual] = {}
        self.oauth_accounts: dict[tuple[str, str], SimpleNamespace] = {}

    async def create_oauth_state(self, _db: object, *, state: str, expires_at: datetime, **kwargs: object) -> object:
        payload = {"state": state, "expires_at": expires_at, **kwargs}
        self.oauth_states[state] = SimpleNamespace(**payload)
        return self.oauth_states[state]

    async def get_oauth_state(self, _db: object, state: str) -> object | None:
        return self.oauth_states.get(state)

    async def delete_oauth_state(self, _db: object, state: str) -> bool:
        return self.oauth_states.pop(state, None) is not None

    async def get_individual_by_id(self, _db: object, individual_id: UUID) -> FakeIndividual | None:
        return self.individuals_by_id.get(individual_id)

    async def get_individual_by_email(self, _db: object, email: str) -> FakeIndividual | None:
        return self.individuals_by_email.get(email)

    async def update_individual(self, _db: object, individual_id: UUID, **updates: object) -> FakeIndividual | None:
        individual = self.individuals_by_id.get(individual_id)
        if individual is None:
            return None
        for key, value in updates.items():
            setattr(individual, key, value)
        return individual


class FakeBelgieClient:
    def __init__(self) -> None:
        self.db = object()
        self.adapter = FakeAdapter()
        self.created_oauth_accounts: list[dict[str, object]] = []
        self.after_sign_up = None

    async def get_individual(self, security_scopes, request):
        return FakeIndividual(
            id=uuid4(),
            email="owner@example.com",
            email_verified_at=datetime.now(UTC),
            name="Owner",
            image=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            scopes=[],
        )

    async def get_oauth_account(self, *, provider: str, provider_account_id: str):
        return self.adapter.oauth_accounts.get((provider, provider_account_id))

    async def get_or_create_individual(
        self,
        email: str,
        *,
        name: str | None = None,
        image: str | None = None,
        email_verified_at: datetime | None = None,
    ) -> tuple[FakeIndividual, bool]:
        if email in self.adapter.individuals_by_email:
            return self.adapter.individuals_by_email[email], False
        individual = FakeIndividual(
            id=uuid4(),
            email=email,
            email_verified_at=email_verified_at,
            name=name,
            image=image,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            scopes=[],
        )
        self.adapter.individuals_by_email[email] = individual
        self.adapter.individuals_by_id[individual.id] = individual
        return individual, True

    async def sign_in_individual(self, individual: FakeIndividual, *, request):
        return SimpleNamespace(id=uuid4(), individual_id=individual.id, request=request)

    async def upsert_oauth_account(self, **payload: object) -> object:
        account = SimpleNamespace(id=uuid4(), **payload)
        self.created_oauth_accounts.append(payload)
        self.adapter.oauth_accounts[(str(payload["provider"]), str(payload["provider_account_id"]))] = account
        return account

    async def update_oauth_account_by_id(self, oauth_account_id: UUID, **payload: object) -> object:
        return SimpleNamespace(id=oauth_account_id, **payload)

    def create_session_cookie(self, session: object, response):
        return response


class FakeOIDCTransport:
    def __init__(self, *, email: str = "person@dept.example.com") -> None:
        self.config = SimpleNamespace(use_pkce=True)
        self.email = email

    def should_use_nonce(self, scopes):
        return True

    async def generate_authorization_url(self, state: str, **kwargs: object) -> str:
        return f"https://idp.example.com/authorize?state={state}"

    async def resolve_server_metadata(self) -> dict[str, str]:
        return {"issuer": "https://idp.example.com"}

    def validate_issuer_parameter(self, issuer: str | None, metadata: dict[str, str]) -> None:
        if issuer is not None and issuer != "https://idp.example.com":
            raise ValueError("issuer mismatch")

    async def exchange_code_for_tokens(self, code: str, *, code_verifier: str | None = None) -> OAuthTokenSet:
        return OAuthTokenSet(
            access_token=f"access-{code}",
            refresh_token="refresh-token",
            token_type="Bearer",
            scope="openid email profile",
            id_token="id-token",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token_expires_at=None,
            raw={"access_token": f"access-{code}", "refresh_token": "refresh-token"},
        )

    async def fetch_provider_profile(self, token_set: OAuthTokenSet, *, nonce: str | None = None) -> OAuthUserInfo:
        return OAuthUserInfo(
            provider_account_id="oidc-user-1",
            email=self.email,
            email_verified=True,
            name="Person Example",
            raw={"sub": "oidc-user-1", "email": self.email, "email_verified": True, "name": "Person Example"},
        )


class FakeSAMLEngine:
    async def metadata_xml(self, *, provider, config, acs_url):
        return f'<EntityDescriptor entityID="{config.entity_id}"><AssertionConsumerService Location="{acs_url}"/></EntityDescriptor>'

    async def start_signin(self, *, provider, config, acs_url, relay_state):
        return SAMLStartResult(
            form_action=config.sso_url,
            form_fields={"RelayState": relay_state, "SAMLRequest": "request"},
            request_id="request-123",
        )

    async def finish_signin(self, *, provider, config, request, relay_state, request_id):
        return SAMLResponseProfile(
            provider_account_id="saml-user-1",
            email="person@example.com",
            email_verified=True,
            name="Saml Person",
            raw={"email": "person@example.com", "request_id": request_id, "relay_state": relay_state},
        )


def build_plugin(*, include_saml: bool = False) -> tuple[SSOPlugin, FakeBelgieClient, FakeOrganizationAdapter]:
    organization_id = uuid4()
    providers = [
        FakeProvider(
            id=uuid4(),
            organization_id=organization_id,
            created_by_individual_id=None,
            provider_type="oidc",
            provider_id="acme",
            issuer="https://idp.example.com",
            oidc_config={
                "issuer": "https://idp.example.com",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
                "userinfo_endpoint": "https://idp.example.com/userinfo",
                "scopes": ["openid", "email", "profile"],
                "token_endpoint_auth_method": "client_secret_basic",
                "use_pkce": True,
                "override_user_info_on_sign_in": False,
                "claim_mapping": {
                    "subject": "sub",
                    "email": "email",
                    "email_verified": "email_verified",
                    "name": "name",
                    "image": "picture",
                },
            },
            saml_config=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]
    if include_saml:
        providers.append(
            FakeProvider(
                id=uuid4(),
                organization_id=organization_id,
                created_by_individual_id=None,
                provider_type="saml",
                provider_id="acme-saml",
                issuer="https://idp.example.com",
                oidc_config=None,
                saml_config={
                    "entity_id": "urn:acme:sp",
                    "sso_url": "https://idp.example.com/saml",
                    "x509_certificate": "certificate",
                    "binding": "redirect",
                    "allow_idp_initiated": True,
                    "want_assertions_signed": True,
                    "sign_authn_request": True,
                    "signature_algorithm": "rsa-sha256",
                    "digest_algorithm": "sha256",
                    "claim_mapping": {
                        "subject": "name_id",
                        "email": "email",
                        "email_verified": "email_verified",
                        "name": "name",
                        "groups": "groups",
                    },
                },
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        )
    domains = [
        FakeDomain(
            id=uuid4(),
            sso_provider_id=providers[0].id,
            domain="example.com",
            verification_token="token",
            verified_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    ]
    settings = EnterpriseSSO(adapter=FakeSSOAdapter(providers, domains), saml_engine=FakeSAMLEngine())
    plugin = SSOPlugin(BelgieSettings(secret="secret", base_url="http://localhost:8000"), settings)
    organization_adapter = FakeOrganizationAdapter(organization_id)
    plugin._organization_plugin_resolved = True
    plugin._organization_plugin = SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter))
    client_dependency = FakeBelgieClient()
    return plugin, client_dependency, organization_adapter


def test_router_no_longer_requires_organization_plugin() -> None:
    plugin, client_dependency, _ = build_plugin()
    plugin._organization_plugin_resolved = True
    plugin._organization_plugin = None
    belgie = DummyBelgie(client_dependency)

    router = plugin.router(belgie)

    assert router is not None


def test_signin_redirects_using_verified_domain_suffix_lookup(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?email=person@dept.example.com", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")


def test_shared_callback_creates_session_and_assigns_org(monkeypatch) -> None:
    plugin, client_dependency, organization_adapter = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?email=person@dept.example.com&redirect_to=%2Fafter",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/after"
    assert len(client_dependency.created_oauth_accounts) == 1
    assert organization_adapter.created_members


def test_callback_redirects_to_error_target_when_email_not_trusted(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FakeOIDCTransport(email="person@untrusted.com"),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?provider_id=acme&error_redirect_url=%2Ferror",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/error?error=signup_disabled")


@pytest.mark.asyncio
async def test_after_authenticate_assigns_verified_google_individual_with_suffix_domain() -> None:
    plugin, client_dependency, organization_adapter = build_plugin()
    belgie = DummyBelgie(client_dependency)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@dept.example.com",
        email_verified_at=datetime.now(UTC),
        name="Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )

    await plugin.after_authenticate(
        belgie=belgie,
        client=client_dependency,
        request=SimpleNamespace(),
        individual=individual,
        profile=AuthenticatedProfile(
            provider="google",
            provider_account_id="google-user-1",
            email=individual.email,
            email_verified=True,
        ),
    )

    assert organization_adapter.created_members == [
        (plugin.settings.adapter.providers["acme"].organization_id, individual.id, "member"),
    ]


def test_saml_metadata_and_signin_routes_use_engine() -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    metadata = client.get("/auth/provider/sso/metadata/acme-saml")
    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)

    assert metadata.status_code == 200
    assert "EntityDescriptor" in metadata.text
    assert signin.status_code == 200
    assert "SAMLRequest" in signin.text
