from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from belgie_sso.client import SSOClient
from belgie_sso.settings import EnterpriseSSO
from belgie_sso.utils import split_provider_domains

if TYPE_CHECKING:
    from belgie_proto.sso import DomainVerificationState


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


@dataclass
class FakeOrganization:
    id: UUID
    name: str
    slug: str
    logo: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeMember:
    id: UUID
    organization_id: UUID
    individual_id: UUID
    role: str
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeProvider:
    id: UUID
    organization_id: UUID | None
    created_by_individual_id: UUID | None
    provider_type: str
    provider_id: str
    issuer: str
    domain: str
    domain_verified: bool
    domain_verification_token: str | None
    domain_verification_token_expires_at: datetime | None
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
    verification_token_expires_at: datetime | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


def build_individual(
    *,
    email: str = "owner@example.com",
    name: str = "Owner",
) -> FakeIndividual:
    now = datetime.now(UTC)
    return FakeIndividual(
        id=uuid4(),
        email=email,
        email_verified_at=now,
        name=name,
        image=None,
        created_at=now,
        updated_at=now,
        scopes=[],
    )


def build_organization(
    *,
    name: str = "Acme",
    slug: str = "acme",
) -> FakeOrganization:
    now = datetime.now(UTC)
    return FakeOrganization(
        id=uuid4(),
        name=name,
        slug=slug,
        logo=None,
        created_at=now,
        updated_at=now,
    )


def build_member(
    *,
    organization_id: UUID,
    individual_id: UUID,
    role: str = "owner",
) -> FakeMember:
    now = datetime.now(UTC)
    return FakeMember(
        id=uuid4(),
        organization_id=organization_id,
        individual_id=individual_id,
        role=role,
        created_at=now,
        updated_at=now,
    )


def build_provider(
    *,
    organization_id: UUID | None = None,
    created_by_individual_id: UUID | None = None,
    provider_type: str = "oidc",
    provider_id: str = "acme",
    issuer: str = "https://idp.example.com",
    domain: str = "",
    domain_verified: bool = False,
    oidc_config: dict[str, str | bool | list[str] | dict[str, str]] | None = None,
    saml_config: dict[str, str | bool | list[str] | dict[str, str]] | None = None,
) -> FakeProvider:
    now = datetime.now(UTC)
    return FakeProvider(
        id=uuid4(),
        organization_id=organization_id,
        created_by_individual_id=created_by_individual_id,
        provider_type=provider_type,
        provider_id=provider_id,
        issuer=issuer,
        domain=domain,
        domain_verified=domain_verified,
        domain_verification_token=None,
        domain_verification_token_expires_at=None,
        oidc_config={} if oidc_config is None and provider_type == "oidc" else oidc_config,
        saml_config=saml_config,
        created_at=now,
        updated_at=now,
    )


def build_domain(
    *,
    sso_provider_id: UUID,
    domain: str = "example.com",
    verification_token: str = "token",  # noqa: S107
    verified_at: datetime | None = None,
) -> FakeDomain:
    now = datetime.now(UTC)
    return FakeDomain(
        id=uuid4(),
        sso_provider_id=sso_provider_id,
        domain=domain,
        verification_token=verification_token,
        verification_token_expires_at=None,
        verified_at=verified_at,
        created_at=now,
        updated_at=now,
    )


class MemorySSOAdapter:
    def __init__(
        self,
        providers: list[FakeProvider] | None = None,
        domains: list[FakeDomain] | None = None,
    ) -> None:
        self.providers: dict[str, FakeProvider] = {}
        self.providers_by_id: dict[UUID, FakeProvider] = {}
        self.domains: dict[UUID, FakeDomain] = {}
        for provider in providers or []:
            self.providers[provider.provider_id] = provider
            self.providers_by_id[provider.id] = provider
        for domain in domains or []:
            self.domains[domain.id] = domain
            if (provider := self.providers_by_id.get(domain.sso_provider_id)) is None:
                continue
            provider_domains = [*split_provider_domains(provider.domain), domain.domain]
            provider.domain = ",".join(dict.fromkeys(provider_domains))
            provider.domain_verified = provider.domain_verified or domain.verified_at is not None
            provider.domain_verification_token = domain.verification_token
            provider.domain_verification_token_expires_at = domain.verification_token_expires_at

    async def create_provider(
        self,
        _session: object,
        *,
        organization_id: UUID | None,
        created_by_individual_id: UUID | None,
        provider_type: str,
        provider_id: str,
        issuer: str,
        domain: str = "",
        domain_verification: DomainVerificationState | None = None,
        oidc_config: dict[str, str | bool | list[str] | dict[str, str]] | None,
        saml_config: dict[str, str | bool | list[str] | dict[str, str]] | None,
    ) -> FakeProvider:
        now = datetime.now(UTC)
        provider = FakeProvider(
            id=uuid4(),
            organization_id=organization_id,
            created_by_individual_id=created_by_individual_id,
            provider_type=provider_type,
            provider_id=provider_id,
            issuer=issuer,
            domain=domain,
            domain_verified=domain_verification.verified if domain_verification is not None else False,
            domain_verification_token=domain_verification.token if domain_verification is not None else None,
            domain_verification_token_expires_at=(
                domain_verification.token_expires_at if domain_verification is not None else None
            ),
            oidc_config=oidc_config,
            saml_config=saml_config,
            created_at=now,
            updated_at=now,
        )
        self.providers[provider.provider_id] = provider
        self.providers_by_id[provider.id] = provider
        self._sync_domains_for_provider(provider)
        return provider

    async def get_provider_by_id(self, _session: object, *, sso_provider_id: UUID) -> FakeProvider | None:
        return self.providers_by_id.get(sso_provider_id)

    async def get_provider_by_provider_id(self, _session: object, *, provider_id: str) -> FakeProvider | None:
        return self.providers.get(provider_id)

    async def get_provider_by_domain(self, _session: object, *, domain: str) -> FakeProvider | None:
        return next(
            (provider for provider in self.providers.values() if domain in split_provider_domains(provider.domain)),
            None,
        )

    async def list_providers_for_organization(self, _session: object, *, organization_id: UUID) -> list[FakeProvider]:
        return [provider for provider in self.providers.values() if provider.organization_id == organization_id]

    async def list_providers_for_individual(self, _session: object, *, individual_id: UUID) -> list[FakeProvider]:
        return [
            provider
            for provider in self.providers.values()
            if provider.created_by_individual_id == individual_id and provider.organization_id is None
        ]

    async def update_provider(
        self,
        _session: object,
        *,
        sso_provider_id: UUID,
        organization_id: UUID | None = None,
        created_by_individual_id: UUID | None = None,
        provider_type: str | None = None,
        issuer: str | None = None,
        domain: str | None = None,
        domain_verification: DomainVerificationState | None = None,
        oidc_config: dict[str, str | bool | list[str] | dict[str, str]] | None = None,
        saml_config: dict[str, str | bool | list[str] | dict[str, str]] | None = None,
    ) -> FakeProvider | None:
        provider = self.providers_by_id.get(sso_provider_id)
        if provider is None:
            return None
        if organization_id is not None:
            provider.organization_id = organization_id
        if created_by_individual_id is not None:
            provider.created_by_individual_id = created_by_individual_id
        if provider_type is not None:
            provider.provider_type = provider_type
        if issuer is not None:
            provider.issuer = issuer
        if domain is not None:
            provider.domain = domain
        if domain_verification is not None:
            provider.domain_verified = domain_verification.verified
            provider.domain_verification_token = domain_verification.token
            provider.domain_verification_token_expires_at = domain_verification.token_expires_at
        if oidc_config is not None:
            provider.oidc_config = oidc_config
        if saml_config is not None:
            provider.saml_config = saml_config
        provider.updated_at = datetime.now(UTC)
        self._sync_domains_for_provider(provider)
        return provider

    async def delete_provider(self, _session: object, *, sso_provider_id: UUID) -> bool:
        provider = self.providers_by_id.pop(sso_provider_id, None)
        if provider is None:
            return False
        self.providers.pop(provider.provider_id, None)
        for domain_id in [domain.id for domain in self.domains.values() if domain.sso_provider_id == sso_provider_id]:
            self.domains.pop(domain_id)
        return True

    async def list_providers_matching_domain(
        self,
        _session: object,
        *,
        domain: str,
        verified_only: bool,
    ) -> list[FakeProvider]:
        return [
            provider
            for provider in self.providers.values()
            if (not verified_only or provider.domain_verified)
            and any(item == domain or domain.endswith(f".{item}") for item in split_provider_domains(provider.domain))
        ]

    async def create_domain(
        self,
        _session: object,
        *,
        sso_provider_id: UUID,
        domain: str,
        verification_token: str,
        verification_token_expires_at: datetime | None = None,
    ) -> FakeDomain:
        now = datetime.now(UTC)
        sso_domain = FakeDomain(
            id=uuid4(),
            sso_provider_id=sso_provider_id,
            domain=domain,
            verification_token=verification_token,
            verification_token_expires_at=verification_token_expires_at,
            verified_at=None,
            created_at=now,
            updated_at=now,
        )
        self.domains[sso_domain.id] = sso_domain
        if (provider := self.providers_by_id.get(sso_provider_id)) is not None:
            domains = list(split_provider_domains(provider.domain))
            if domain not in domains:
                domains.append(domain)
                provider.domain = ",".join(domains)
            provider.domain_verification_token = verification_token
            provider.domain_verification_token_expires_at = verification_token_expires_at
            provider.domain_verified = False
            provider.updated_at = now
        return sso_domain

    async def get_domain(self, _session: object, *, domain_id: UUID) -> FakeDomain | None:
        return self.domains.get(domain_id)

    async def get_domain_by_name(self, _session: object, *, domain: str) -> FakeDomain | None:
        return next((item for item in self.domains.values() if item.domain == domain), None)

    async def get_verified_domain(self, _session: object, *, domain: str) -> FakeDomain | None:
        return next(
            (item for item in self.domains.values() if item.domain == domain and item.verified_at is not None),
            None,
        )

    async def list_verified_domains_matching(self, _session: object, *, domain: str) -> list[FakeDomain]:
        return [
            item
            for item in self.domains.values()
            if item.verified_at is not None and (item.domain == domain or domain.endswith(f".{item.domain}"))
        ]

    async def list_domains_matching(self, _session: object, *, domain: str) -> list[FakeDomain]:
        return [item for item in self.domains.values() if item.domain == domain or domain.endswith(f".{item.domain}")]

    async def list_domains_for_provider(self, _session: object, *, sso_provider_id: UUID) -> list[FakeDomain]:
        return [item for item in self.domains.values() if item.sso_provider_id == sso_provider_id]

    async def update_domain(
        self,
        _session: object,
        *,
        domain_id: UUID,
        verification_token: str | None = None,
        verification_token_expires_at: datetime | None = None,
        verified_at: datetime | None = None,
    ) -> FakeDomain | None:
        sso_domain = self.domains.get(domain_id)
        if sso_domain is None:
            return None
        if verification_token is not None:
            sso_domain.verification_token = verification_token
        if verification_token_expires_at is not None:
            sso_domain.verification_token_expires_at = verification_token_expires_at
        sso_domain.verified_at = verified_at
        sso_domain.updated_at = datetime.now(UTC)
        if (provider := self.providers_by_id.get(sso_domain.sso_provider_id)) is not None:
            provider.domain_verification_token = sso_domain.verification_token
            provider.domain_verification_token_expires_at = sso_domain.verification_token_expires_at
            provider.domain_verified = sso_domain.verified_at is not None
            provider.updated_at = sso_domain.updated_at
        return sso_domain

    async def delete_domain(self, _session: object, *, domain_id: UUID) -> bool:
        if domain_id not in self.domains:
            return False
        domain = self.domains.pop(domain_id)
        if (provider := self.providers_by_id.get(domain.sso_provider_id)) is not None:
            provider.domain = ",".join(
                item for item in split_provider_domains(provider.domain) if item != domain.domain
            )
            provider.domain_verified = False
            provider.domain_verification_token = None
            provider.domain_verification_token_expires_at = None
            provider.updated_at = datetime.now(UTC)
        return True

    async def delete_domains_for_provider(self, _session: object, *, sso_provider_id: UUID) -> int:
        domain_ids = [item.id for item in self.domains.values() if item.sso_provider_id == sso_provider_id]
        for domain_id in domain_ids:
            self.domains.pop(domain_id)
        if (provider := self.providers_by_id.get(sso_provider_id)) is not None:
            provider.domain = ""
            provider.domain_verified = False
            provider.domain_verification_token = None
            provider.domain_verification_token_expires_at = None
        return len(domain_ids)

    def _sync_domains_for_provider(self, provider: FakeProvider) -> None:
        existing_domains = {
            domain.domain: domain for domain in self.domains.values() if domain.sso_provider_id == provider.id
        }
        active_domains = set(split_provider_domains(provider.domain))
        for domain_id, domain in list(self.domains.items()):
            if domain.sso_provider_id == provider.id and domain.domain not in active_domains:
                self.domains.pop(domain_id)
        for domain in active_domains:
            if domain in existing_domains:
                existing = existing_domains[domain]
                existing.verification_token = provider.domain_verification_token or existing.verification_token
                existing.verification_token_expires_at = provider.domain_verification_token_expires_at
                existing.verified_at = provider.updated_at if provider.domain_verified else None
                existing.updated_at = provider.updated_at
                continue
            domain_id = uuid4()
            self.domains[domain_id] = FakeDomain(
                id=domain_id,
                sso_provider_id=provider.id,
                domain=domain,
                verification_token=provider.domain_verification_token or "",
                verification_token_expires_at=provider.domain_verification_token_expires_at,
                verified_at=provider.updated_at if provider.domain_verified else None,
                created_at=provider.created_at,
                updated_at=provider.updated_at,
            )


class MemoryOrganizationAdapter:
    def __init__(
        self,
        organization: FakeOrganization | None = None,
        member: FakeMember | None = None,
    ) -> None:
        self.organizations: dict[UUID, FakeOrganization] = {}
        self.members: dict[tuple[UUID, UUID], FakeMember] = {}
        self.created_members: list[tuple[UUID, UUID, str]] = []
        self.member = member
        if organization is not None:
            self.organizations[organization.id] = organization
        if member is not None:
            self.members[(member.organization_id, member.individual_id)] = member

    def add_organization(self, organization: FakeOrganization) -> None:
        self.organizations[organization.id] = organization

    def add_member(self, member: FakeMember) -> None:
        self.member = member
        self.members[(member.organization_id, member.individual_id)] = member

    async def get_organization_by_id(self, _session: object, organization_id: UUID) -> FakeOrganization | None:
        return self.organizations.get(organization_id)

    async def get_organization_by_slug(self, _session: object, slug: str) -> FakeOrganization | None:
        return next((organization for organization in self.organizations.values() if organization.slug == slug), None)

    async def get_member(self, _session: object, *, organization_id: UUID, individual_id: UUID) -> FakeMember | None:
        return self.members.get((organization_id, individual_id))

    async def create_member(self, _session: object, *, organization_id: UUID, individual_id: UUID, role: str) -> object:
        self.created_members.append((organization_id, individual_id, role))
        self.members[(organization_id, individual_id)] = build_member(
            organization_id=organization_id,
            individual_id=individual_id,
            role=role,
        )
        return object()


def build_client(
    *,
    role: str = "owner",
    providers_limit: int | None = 2,
) -> tuple[SSOClient, MemorySSOAdapter, FakeOrganization, FakeIndividual]:
    admin_individual = build_individual()
    organization = build_organization()
    member = build_member(
        organization_id=organization.id,
        individual_id=admin_individual.id,
        role=role,
    )
    sso_adapter = MemorySSOAdapter()
    organization_adapter = MemoryOrganizationAdapter(organization, member)
    settings = EnterpriseSSO(adapter=sso_adapter, providers_limit=providers_limit)
    client = SSOClient(
        client=SimpleNamespace(db=object()),
        base_url="https://app.example.com",
        settings=settings,
        organization_adapter=organization_adapter,
        current_individual=admin_individual,
    )
    return client, sso_adapter, organization, admin_individual
