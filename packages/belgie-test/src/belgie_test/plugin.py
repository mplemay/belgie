from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import time
from typing import TYPE_CHECKING, NotRequired, TypedDict
from urllib.parse import urlparse
from uuid import UUID, uuid4

from belgie_core.core.plugin import PluginClient
from belgie_proto.core.connection import DBConnection
from belgie_proto.core.individual import IndividualProtocol
from belgie_proto.core.json import JSONValue
from belgie_proto.core.session import SessionProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from fastapi import APIRouter

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_organization.plugin import OrganizationPlugin


class TestCookie(TypedDict):
    name: str
    value: str
    domain: str
    path: str
    httpOnly: bool
    secure: bool
    sameSite: str
    expires: NotRequired[int]


@dataclass(slots=True, kw_only=True, frozen=True)
class IndividualData:
    email: str
    name: str | None
    image: str | None
    email_verified_at: datetime | None
    scopes: list[str] = field(default_factory=list)
    custom_fields: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True, frozen=True)
class OrganizationData:
    name: str
    slug: str
    logo: str | None


@dataclass(slots=True, kw_only=True, frozen=True)
class LoginResult:
    session: SessionProtocol
    individual: IndividualProtocol[str]
    headers: dict[str, str]
    cookies: list[TestCookie]
    token: str


@dataclass(slots=True, kw_only=True, frozen=True)
class TestUtils:
    def __call__(self, belgie_settings: BelgieSettings) -> TestUtilsPlugin:
        return TestUtilsPlugin(belgie_settings)


class OrganizationTestUtils:
    def __init__(self, plugin: OrganizationPlugin) -> None:
        self._plugin = plugin

    def create_organization(
        self,
        *,
        name: str = "Test Organization",
        slug: str | None = None,
        logo: str | None = None,
    ) -> OrganizationData:
        return OrganizationData(
            name=name,
            slug=slug or _slug_for_name(name),
            logo=logo,
        )

    async def save_organization(
        self,
        db: DBConnection,
        organization: OrganizationData,
    ) -> OrganizationProtocol:
        return await self._plugin.settings.adapter.create_organization(
            db,
            name=organization.name,
            slug=organization.slug,
            logo=organization.logo,
        )

    async def delete_organization(self, db: DBConnection, organization_id: UUID) -> bool:
        return await self._plugin.settings.adapter.delete_organization(db, organization_id)

    async def add_member(
        self,
        db: DBConnection,
        *,
        individual_id: UUID,
        organization_id: UUID,
        role: str = "member",
    ) -> MemberProtocol:
        return await self._plugin.settings.adapter.create_member(
            db,
            organization_id=organization_id,
            individual_id=individual_id,
            role=role,
        )


class TestUtilsPlugin(PluginClient):
    def __init__(self, belgie_settings: BelgieSettings) -> None:
        self._belgie_settings = belgie_settings
        self._belgie: Belgie | None = None

    def bind_belgie(self, belgie: Belgie) -> None:
        self._belgie = belgie

    @property
    def organization(self) -> OrganizationTestUtils | None:
        plugin = self._organization_plugin()
        return None if plugin is None else OrganizationTestUtils(plugin)

    def create_individual(
        self,
        *,
        email: str | None = None,
        name: str | None = "Test Individual",
        image: str | None = None,
        email_verified: bool = True,
        email_verified_at: datetime | None = None,
        scopes: Sequence[str] | None = None,
        custom_fields: Mapping[str, JSONValue] | None = None,
        **extra_fields: JSONValue,
    ) -> IndividualData:
        return IndividualData(
            email=email or f"test-{uuid4().hex[:8]}@example.com",
            name=name,
            image=image,
            email_verified_at=email_verified_at or (datetime.now(UTC) if email_verified else None),
            scopes=list(scopes or []),
            custom_fields={
                **dict(custom_fields or {}),
                **extra_fields,
            },
        )

    async def save_individual(
        self,
        db: DBConnection,
        individual: IndividualData,
    ) -> IndividualProtocol[str]:
        belgie = self._require_belgie()
        saved = await belgie.adapter.create_individual(
            db,
            email=individual.email,
            name=individual.name,
            image=individual.image,
            email_verified_at=individual.email_verified_at,
        )
        updates: dict[str, JSONValue] = dict(individual.custom_fields)
        if individual.scopes:
            scope_values: list[JSONValue] = [scope for scope in individual.scopes]
            updates["scopes"] = scope_values
        if not updates:
            return saved

        updated = await belgie.adapter.update_individual(db, saved.id, **updates)
        if updated is None:
            msg = "failed to update saved individual"
            raise RuntimeError(msg)
        return updated

    async def delete_individual(self, db: DBConnection, individual_id: UUID) -> bool:
        return await self._require_belgie().adapter.delete_individual(db, individual_id)

    async def login(self, db: DBConnection, *, individual_id: UUID) -> LoginResult:
        belgie = self._require_belgie()
        individual = await belgie.adapter.get_individual_by_id(db, individual_id)
        if individual is None:
            msg = f"individual not found: {individual_id}"
            raise ValueError(msg)

        session = await belgie.session_manager.create_session(db, individual_id=individual_id)
        token = str(session.id)
        return LoginResult(
            session=session,
            individual=individual,
            headers=self._headers_for_token(token),
            cookies=self._cookies_for_token(token),
            token=token,
        )

    async def get_auth_headers(self, db: DBConnection, *, individual_id: UUID) -> dict[str, str]:
        session = await self._require_belgie().session_manager.create_session(db, individual_id=individual_id)
        return self._headers_for_token(str(session.id))

    async def get_cookies(
        self,
        db: DBConnection,
        *,
        individual_id: UUID,
        domain: str | None = None,
    ) -> list[TestCookie]:
        session = await self._require_belgie().session_manager.create_session(db, individual_id=individual_id)
        return self._cookies_for_token(str(session.id), domain=domain)

    def router(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None

    def _headers_for_token(self, token: str) -> dict[str, str]:
        return {"cookie": f"{self._belgie_settings.cookie.name}={token}"}

    def _cookies_for_token(self, token: str, *, domain: str | None = None) -> list[TestCookie]:
        cookie: TestCookie = {
            "name": self._belgie_settings.cookie.name,
            "value": token,
            "domain": domain or _domain_from_base_url(self._belgie_settings.base_url),
            "path": "/",
            "httpOnly": self._belgie_settings.cookie.http_only,
            "secure": self._belgie_settings.cookie.secure,
            "sameSite": _same_site_value(self._belgie_settings.cookie.same_site),
            "expires": int(time()) + self._belgie_settings.session.max_age,
        }
        return [cookie]

    def _organization_plugin(self) -> OrganizationPlugin | None:
        if self._belgie is None:
            return None
        try:
            from belgie_organization.plugin import OrganizationPlugin  # noqa: PLC0415
        except ModuleNotFoundError:
            return None
        return next(
            (plugin for plugin in self._belgie.plugins if isinstance(plugin, OrganizationPlugin)),
            None,
        )

    def _require_belgie(self) -> Belgie:
        if self._belgie is None:
            msg = "TestUtilsPlugin must be registered with Belgie.add_plugin before use"
            raise RuntimeError(msg)
        return self._belgie


def _domain_from_base_url(base_url: str) -> str:
    if hostname := urlparse(base_url).hostname:
        return hostname
    return "localhost"


def _same_site_value(same_site: str) -> str:
    match same_site:
        case "strict":
            return "Strict"
        case "none":
            return "None"
        case _:
            return "Lax"


def _slug_for_name(name: str) -> str:
    normalized = "-".join(name.lower().split())
    return f"{normalized}-{uuid4().hex[:4]}"
