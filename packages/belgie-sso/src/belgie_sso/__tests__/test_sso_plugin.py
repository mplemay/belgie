from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import UUID, uuid4

import jwt
import pytest
from belgie_core.core.exceptions import OAuthError
from belgie_core.core.plugin import AuthenticatedProfile
from belgie_core.core.settings import BelgieSettings
from belgie_proto.sso import OIDCProviderConfig
from belgie_sso.plugin import NormalizedOIDCProfile, SSOPlugin, TokenResponse
from belgie_sso.settings import EnterpriseSSO
from belgie_sso.utils import deserialize_oidc_config
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


@dataclass
class FakeProvider:
    id: UUID
    organization_id: UUID
    provider_id: str
    issuer: str
    oidc_config: dict[str, str | bool | list[str] | dict[str, str | dict[str, str]]]
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


class DummyBelgie:
    def __init__(self, client: object) -> None:
        self._client = client
        self.plugins: list[object] = []
        self.after_authenticate = AsyncMock()
        self.settings = SimpleNamespace(
            base_url="http://localhost:8000",
            urls=SimpleNamespace(signin_redirect="/dashboard"),
        )

    async def __call__(self) -> object:
        return self._client


class FakeSSOAdapter:
    def __init__(self, provider: FakeProvider, domains: list[FakeDomain]) -> None:
        self.provider = provider
        self.domains = domains

    async def create_provider(
        self,
        _db: object,
        *,
        organization_id: UUID,  # noqa: ARG002
        provider_id: str,  # noqa: ARG002
        issuer: str,  # noqa: ARG002
        oidc_config: dict[str, str | bool | list[str] | dict[str, str | dict[str, str]]],  # noqa: ARG002
    ) -> FakeProvider:
        return self.provider

    async def get_provider_by_provider_id(self, _db: object, *, provider_id: str) -> FakeProvider | None:
        if provider_id == self.provider.provider_id:
            return self.provider
        return None

    async def get_provider_by_id(self, _db: object, *, sso_provider_id: UUID) -> FakeProvider | None:
        if sso_provider_id == self.provider.id:
            return self.provider
        return None

    async def list_domains_for_provider(self, _db: object, *, sso_provider_id: UUID) -> list[FakeDomain]:
        if sso_provider_id == self.provider.id:
            return list(self.domains)
        return []

    async def get_verified_domain(self, _db: object, *, domain: str) -> FakeDomain | None:
        return next((item for item in self.domains if item.domain == domain and item.verified_at is not None), None)

    async def get_best_verified_domain(self, _db: object, *, domain: str) -> FakeDomain | None:
        matches = [
            item
            for item in self.domains
            if item.verified_at is not None and (domain == item.domain or domain.endswith(f".{item.domain}"))
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: len(item.domain), reverse=True)
        return matches[0]

    async def list_providers_for_organization(self, _db: object, *, organization_id: UUID) -> list[FakeProvider]:
        if organization_id == self.provider.organization_id:
            return [self.provider]
        return []

    async def update_provider(
        self,
        _db: object,
        *,
        sso_provider_id: UUID,
        issuer: str | None = None,  # noqa: ARG002
        oidc_config: dict[str, str | bool | list[str] | dict[str, str | dict[str, str]]] | None = None,  # noqa: ARG002
    ) -> FakeProvider | None:
        if sso_provider_id != self.provider.id:
            return None
        return self.provider

    async def delete_provider(self, _db: object, *, sso_provider_id: UUID) -> bool:
        return sso_provider_id == self.provider.id

    async def create_domain(
        self,
        _db: object,
        *,
        sso_provider_id: UUID,
        domain: str,
        verification_token: str,
    ) -> FakeDomain:
        created = FakeDomain(
            id=uuid4(),
            sso_provider_id=sso_provider_id,
            domain=domain,
            verification_token=verification_token,
            verified_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.domains.append(created)
        return created

    async def get_domain(self, _db: object, *, domain_id: UUID) -> FakeDomain | None:
        return next((item for item in self.domains if item.id == domain_id), None)

    async def get_domain_by_name(self, _db: object, *, domain: str) -> FakeDomain | None:
        return next((item for item in self.domains if item.domain == domain), None)

    async def update_domain(
        self,
        _db: object,
        *,
        domain_id: UUID,
        verification_token: str | None = None,
        verified_at: datetime | None = None,
    ) -> FakeDomain | None:
        domain = await self.get_domain(_db, domain_id=domain_id)
        if domain is None:
            return None
        if verification_token is not None:
            domain.verification_token = verification_token
        domain.verified_at = verified_at
        domain.updated_at = datetime.now(UTC)
        return domain

    async def delete_domain(self, _db: object, *, domain_id: UUID) -> bool:
        before = len(self.domains)
        self.domains = [item for item in self.domains if item.id != domain_id]
        return len(self.domains) < before

    async def delete_domains_for_provider(self, _db: object, *, sso_provider_id: UUID) -> int:
        removed = [item for item in self.domains if item.sso_provider_id == sso_provider_id]
        self.domains = [item for item in self.domains if item.sso_provider_id != sso_provider_id]
        return len(removed)


class FakeOrganizationAdapter:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.members: dict[UUID, str] = {}
        self.created_members: list[tuple[UUID, UUID, str]] = []

    async def get_organization_by_id(self, _db: object, organization_id: UUID) -> object | None:
        if organization_id == self.organization_id:
            return object()
        return None

    async def get_member(self, _db: object, *, organization_id: UUID, individual_id: UUID) -> object | None:
        if organization_id != self.organization_id:
            return None
        if individual_id in self.members:
            return SimpleNamespace(role=self.members[individual_id])
        return None

    async def create_member(self, _db: object, *, organization_id: UUID, individual_id: UUID, role: str) -> object:
        self.members[individual_id] = role
        self.created_members.append((organization_id, individual_id, role))
        return SimpleNamespace(id=uuid4())


def build_plugin(
    *,
    verified: bool = True,
    **settings_kwargs: object,
) -> tuple[SSOPlugin, FakeSSOAdapter, FakeOrganizationAdapter]:
    organization_id = uuid4()
    provider = FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        provider_id="acme",
        issuer="https://idp.example.com",
        oidc_config={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
            "scopes": ["openid", "email", "profile"],
            "token_endpoint_auth_method": "client_secret_basic",
            "claim_mapping": {
                "subject": "sub",
                "email": "email",
                "email_verified": "email_verified",
                "name": "name",
                "image": "picture",
            },
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    domain = FakeDomain(
        id=uuid4(),
        sso_provider_id=provider.id,
        domain="example.com",
        verification_token="token",
        verified_at=datetime.now(UTC) if verified else None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    settings = EnterpriseSSO(adapter=FakeSSOAdapter(provider, [domain]), **settings_kwargs)
    plugin = SSOPlugin(BelgieSettings(secret="secret", base_url="http://localhost:8000"), settings)
    organization_adapter = FakeOrganizationAdapter(provider.organization_id)
    return plugin, settings.adapter, organization_adapter


def build_normalized_profile(
    *,
    email: str = "person@example.com",
    email_verified: bool = False,
) -> NormalizedOIDCProfile:
    return NormalizedOIDCProfile(
        subject="oidc-user-1",
        email=email,
        email_verified=email_verified,
        name="Person Example",
        image="https://example.com/avatar.png",
        user_info={
            "sub": "oidc-user-1",
            "email": email,
            "email_verified": email_verified,
            "name": "Person Example",
            "picture": "https://example.com/avatar.png",
            "id": "oidc-user-1",
            "image": "https://example.com/avatar.png",
        },
    )


def test_router_requires_organization_plugin() -> None:
    plugin, _, _ = build_plugin()
    belgie = DummyBelgie(client=SimpleNamespace())

    with pytest.raises(RuntimeError, match="belgie-organization"):
        plugin.router(belgie)


def test_signin_invalid_provider_id_returns_400(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(create_oauth_state=AsyncMock()),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/sso/signin?provider_id=acme!",
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_callback_invalid_provider_id_returns_400(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=SimpleNamespace(redirect_url=None)),
        delete_oauth_state=AsyncMock(return_value=True),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        sign_up=AsyncMock(),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/sso/callback/acme!?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_signin_redirects_using_verified_domain_lookup(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(create_oauth_state=AsyncMock()),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/sso/signin?email=person@example.com&redirect_to=%2Fafter",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")
    assert "code_challenge=" in response.headers["location"]
    assert "code_challenge_method=S256" in response.headers["location"]
    client_dependency.adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        code_verifier=ANY,
        redirect_url="/after",
        request_sign_up=False,
    )


def test_callback_creates_session_and_assigns_org(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    oauth_state = SimpleNamespace(redirect_url="/custom-target", code_verifier="verifier", request_sign_up=False)
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
        get_individual_by_email=AsyncMock(return_value=None),
    )
    user = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(id=uuid4())
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )
    monkeypatch.setattr(
        plugin,
        "_get_provider_config",
        AsyncMock(return_value=deserialize_oidc_config(plugin.settings.adapter.provider.oidc_config)),
    )
    monkeypatch.setattr(
        plugin,
        "_exchange_code_for_tokens",
        AsyncMock(
            return_value=TokenResponse(
                access_token="access-token",
                token_type="Bearer",
                refresh_token="refresh-token",
                scope="openid email profile",
                id_token="id-token",
                expires_at=None,
            ),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "_get_claims",
        AsyncMock(
            return_value={
                "sub": "oidc-user-1",
                "email": "person@example.com",
                "email_verified": True,
                "name": "Person Example",
                "picture": "https://example.com/avatar.png",
            },
        ),
    )
    monkeypatch.setattr(
        plugin,
        "_resolve_user_session",
        AsyncMock(return_value=(user, session, True)),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/sso/callback/acme?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/custom-target"
    plugin._exchange_code_for_tokens.assert_awaited_once_with(
        config=deserialize_oidc_config(plugin.settings.adapter.provider.oidc_config),
        code="test-code",
        redirect_uri="http://localhost:8000/auth/provider/sso/callback/acme",
        code_verifier="verifier",
    )
    client_dependency.upsert_oauth_account.assert_awaited_once_with(
        individual_id=user.id,
        provider="sso:acme",
        provider_account_id="oidc-user-1",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=None,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )
    client_dependency.create_session_cookie.assert_called_once_with(session, ANY)
    assert organization_adapter.created_members == [
        (plugin.settings.adapter.provider.organization_id, user.id, "member"),
    ]
    belgie.after_authenticate.assert_awaited_once()


def test_callback_rejects_unverified_domain(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin(verified=False)
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=SimpleNamespace(redirect_url=None, code_verifier="verifier")),
        delete_oauth_state=AsyncMock(return_value=True),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )
    monkeypatch.setattr(
        plugin,
        "_get_provider_config",
        AsyncMock(return_value=deserialize_oidc_config(plugin.settings.adapter.provider.oidc_config)),
    )
    monkeypatch.setattr(
        plugin,
        "_exchange_code_for_tokens",
        AsyncMock(
            return_value=TokenResponse(
                access_token="access-token",
                token_type="Bearer",
                refresh_token=None,
                scope=None,
                id_token=None,
                expires_at=None,
            ),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "_get_claims",
        AsyncMock(
            return_value={
                "sub": "oidc-user-1",
                "email": "person@example.com",
                "email_verified": True,
            },
        ),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    with pytest.raises(OAuthError, match="email domain is not verified"):
        TestClient(app).get(
            "/auth/provider/sso/callback/acme?code=test-code&state=test-state",
            follow_redirects=False,
        )


@pytest.mark.asyncio
async def test_after_authenticate_assigns_verified_google_individual(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    belgie = DummyBelgie(SimpleNamespace())
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )
    individual = SimpleNamespace(id=uuid4())

    await plugin.after_authenticate(
        belgie=belgie,
        client=SimpleNamespace(db=object()),
        request=MagicMock(),
        individual=individual,
        profile=AuthenticatedProfile(
            provider="google",
            provider_account_id="google-user-1",
            email="person@example.com",
            email_verified=True,
        ),
    )

    assert organization_adapter.created_members == [
        (plugin.settings.adapter.provider.organization_id, individual.id, "member"),
    ]


@pytest.mark.asyncio
async def test_after_authenticate_skips_unverified_social_email(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    belgie = DummyBelgie(SimpleNamespace())
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )

    await plugin.after_authenticate(
        belgie=belgie,
        client=SimpleNamespace(db=object()),
        request=MagicMock(),
        individual=SimpleNamespace(id=uuid4()),
        profile=AuthenticatedProfile(
            provider="google",
            provider_account_id="google-user-1",
            email="person@example.com",
            email_verified=False,
        ),
    )

    assert organization_adapter.created_members == []


def test_signin_persists_request_sign_up_and_login_hint(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(create_oauth_state=AsyncMock()),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/sso/signin?provider_id=acme&login_hint=person%40example.com&request_sign_up=true",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "login_hint=person%40example.com" in response.headers["location"]
    client_dependency.adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        code_verifier=ANY,
        redirect_url=None,
        request_sign_up=True,
    )


def test_callback_rejects_implicit_signup_when_request_not_set(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin(disable_implicit_sign_up=True)
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(
            return_value=SimpleNamespace(
                redirect_url=None,
                code_verifier="verifier",
                request_sign_up=False,
            ),
        ),
        delete_oauth_state=AsyncMock(return_value=True),
        get_individual_by_email=AsyncMock(return_value=None),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )
    monkeypatch.setattr(
        plugin,
        "_get_provider_config",
        AsyncMock(return_value=deserialize_oidc_config(plugin.settings.adapter.provider.oidc_config)),
    )
    monkeypatch.setattr(
        plugin,
        "_exchange_code_for_tokens",
        AsyncMock(
            return_value=TokenResponse(
                access_token="access-token",
                token_type="Bearer",
                refresh_token=None,
                scope=None,
                id_token="id-token",
                expires_at=None,
            ),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "_get_claims",
        AsyncMock(
            return_value={
                "sub": "oidc-user-1",
                "email": "person@example.com",
                "email_verified": False,
            },
        ),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    with pytest.raises(OAuthError, match="implicit sign up is disabled"):
        TestClient(app).get(
            "/auth/provider/sso/callback/acme?code=test-code&state=test-state",
            follow_redirects=False,
        )


def test_callback_calls_provision_user_for_returning_user_when_enabled(monkeypatch) -> None:
    provision_user = AsyncMock()
    plugin, _, organization_adapter = build_plugin(
        provision_user=provision_user,
        provision_user_on_every_login=True,
    )
    oauth_state = SimpleNamespace(redirect_url="/custom-target", code_verifier="verifier", request_sign_up=False)
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
        get_individual_by_email=AsyncMock(return_value=SimpleNamespace(id=uuid4(), email_verified_at=None)),
    )
    user = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(id=uuid4())
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )
    monkeypatch.setattr(
        plugin,
        "_get_provider_config",
        AsyncMock(return_value=deserialize_oidc_config(plugin.settings.adapter.provider.oidc_config)),
    )
    monkeypatch.setattr(
        plugin,
        "_exchange_code_for_tokens",
        AsyncMock(
            return_value=TokenResponse(
                access_token="access-token",
                token_type="Bearer",
                refresh_token=None,
                scope=None,
                id_token="id-token",
                expires_at=None,
            ),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "_get_claims",
        AsyncMock(
            return_value={
                "sub": "oidc-user-1",
                "email": "person@example.com",
                "email_verified": False,
                "name": "Person Example",
            },
        ),
    )
    monkeypatch.setattr(
        plugin,
        "_resolve_user_session",
        AsyncMock(return_value=(user, session, False)),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/sso/callback/acme?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    provision_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_after_authenticate_respects_configured_provider_allowlist(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin(domain_assignment_providers=("github",))
    belgie = DummyBelgie(SimpleNamespace())
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )

    await plugin.after_authenticate(
        belgie=belgie,
        client=SimpleNamespace(db=object()),
        request=MagicMock(),
        individual=SimpleNamespace(id=uuid4()),
        profile=AuthenticatedProfile(
            provider="google",
            provider_account_id="google-user-1",
            email="person@example.com",
            email_verified=True,
        ),
    )

    assert organization_adapter.created_members == []


@pytest.mark.asyncio
async def test_get_id_token_claims_verifies_token(monkeypatch) -> None:
    plugin, _, _ = build_plugin()
    config = OIDCProviderConfig(
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://idp.example.com/token",
        jwks_uri="https://idp.example.com/jwks",
    )
    secret = "shared-secret-with-at-least-thirty-two-bytes"  # noqa: S105
    token = jwt.encode(
        {
            "sub": "oidc-user-1",
            "email": "person@example.com",
            "aud": "client-id",
            "iss": "https://idp.example.com",
        },
        secret,
        algorithm="HS256",
    )
    monkeypatch.setattr(
        "belgie_sso.plugin.PyJWKClient.get_signing_key_from_jwt",
        lambda _self, _token: SimpleNamespace(key=secret),
    )

    claims = await plugin._get_id_token_claims(
        provider=plugin.settings.adapter.provider,
        config=config,
        id_token=token,
    )

    assert claims["sub"] == "oidc-user-1"


@pytest.mark.asyncio
async def test_resolve_user_session_updates_existing_user_when_override_and_trust_are_enabled() -> None:
    plugin, _, _ = build_plugin(trust_email_verified=True, default_override_user_info=True)
    existing_user = SimpleNamespace(id=uuid4(), email_verified_at=None)
    updated_user = SimpleNamespace(id=existing_user.id, email_verified_at=datetime.now(UTC))
    session = SimpleNamespace(id=uuid4())
    client = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(update_individual=AsyncMock(return_value=updated_user)),
        sign_in_individual=AsyncMock(return_value=session),
    )

    user, returned_session, is_register = await plugin._resolve_user_session(
        client=client,
        request=MagicMock(),
        email="person@example.com",
        profile=build_normalized_profile(email_verified=True),
        existing_user=existing_user,
        config=OIDCProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            token_endpoint="https://idp.example.com/token",
            override_user_info=False,
        ),
    )

    assert is_register is False
    assert returned_session is session
    assert user is updated_user
    client.adapter.update_individual.assert_awaited_once()
    client.sign_in_individual.assert_awaited_once_with(updated_user, request=ANY)
