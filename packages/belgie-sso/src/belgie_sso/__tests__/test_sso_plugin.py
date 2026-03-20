from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from belgie_core.core.exceptions import OAuthError
from belgie_core.core.plugin import AuthenticatedProfile
from belgie_core.core.settings import BelgieSettings
from belgie_sso.plugin import SSOPlugin, TokenResponse
from belgie_sso.settings import EnterpriseSSO
from fastapi import FastAPI
from fastapi.testclient import TestClient


@dataclass
class FakeProvider:
    id: UUID
    organization_id: UUID
    provider_id: str
    issuer: str
    oidc_config: dict[str, str | list[str] | dict[str, str]]
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
        oidc_config: dict[str, str | list[str] | dict[str, str]],  # noqa: ARG002
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
        oidc_config: dict[str, str | list[str] | dict[str, str]] | None = None,  # noqa: ARG002
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

    async def get_member(self, _db: object, *, organization_id: UUID, user_id: UUID) -> object | None:
        if organization_id != self.organization_id:
            return None
        if user_id in self.members:
            return SimpleNamespace(role=self.members[user_id])
        return None

    async def create_member(self, _db: object, *, organization_id: UUID, user_id: UUID, role: str) -> object:
        self.members[user_id] = role
        self.created_members.append((organization_id, user_id, role))
        return SimpleNamespace(id=uuid4())


def build_plugin(*, verified: bool = True) -> tuple[SSOPlugin, FakeSSOAdapter, FakeOrganizationAdapter]:
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
    settings = EnterpriseSSO(adapter=FakeSSOAdapter(provider, [domain]))
    plugin = SSOPlugin(BelgieSettings(secret="secret", base_url="http://localhost:8000"), settings)
    organization_adapter = FakeOrganizationAdapter(provider.organization_id)
    return plugin, settings.adapter, organization_adapter


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
    app.include_router(plugin.router(belgie), prefix="/auth")

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
    app.include_router(plugin.router(belgie), prefix="/auth")

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
    app.include_router(plugin.router(belgie), prefix="/auth")

    response = TestClient(app).get(
        "/auth/provider/sso/signin?email=person@example.com&redirect_to=%2Fafter",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")
    client_dependency.adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        redirect_url="/after",
    )


def test_callback_creates_session_and_assigns_org(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    oauth_state = SimpleNamespace(redirect_url="/custom-target")
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
    )
    user = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(id=uuid4())
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        sign_up=AsyncMock(return_value=(user, session)),
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
        "get_user_info",
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

    app = FastAPI()
    app.include_router(plugin.router(belgie), prefix="/auth")

    response = TestClient(app).get(
        "/auth/provider/sso/callback/acme?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/custom-target"
    client_dependency.upsert_oauth_account.assert_awaited_once_with(
        user_id=user.id,
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


def test_callback_rejects_unverified_domain(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin(verified=False)
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
        "get_user_info",
        AsyncMock(
            return_value={
                "sub": "oidc-user-1",
                "email": "person@example.com",
                "email_verified": True,
            },
        ),
    )

    app = FastAPI()
    app.include_router(plugin.router(belgie), prefix="/auth")

    with pytest.raises(OAuthError, match="email domain is not verified"):
        TestClient(app).get(
            "/auth/provider/sso/callback/acme?code=test-code&state=test-state",
            follow_redirects=False,
        )


@pytest.mark.asyncio
async def test_after_authenticate_assigns_verified_google_user(monkeypatch) -> None:
    plugin, _, organization_adapter = build_plugin()
    belgie = DummyBelgie(SimpleNamespace())
    monkeypatch.setattr(
        plugin,
        "_ensure_organization_plugin",
        lambda _belgie: SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter)),
    )
    user = SimpleNamespace(id=uuid4())

    await plugin.after_authenticate(
        belgie=belgie,
        client=SimpleNamespace(db=object()),
        request=MagicMock(),
        user=user,
        profile=AuthenticatedProfile(
            provider="google",
            provider_account_id="google-user-1",
            email="person@example.com",
            email_verified=True,
        ),
    )

    assert organization_adapter.created_members == [
        (plugin.settings.adapter.provider.organization_id, user.id, "member"),
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
        user=SimpleNamespace(id=uuid4()),
        profile=AuthenticatedProfile(
            provider="google",
            provider_account_id="google-user-1",
            email="person@example.com",
            email_verified=False,
        ),
    )

    assert organization_adapter.created_members == []
