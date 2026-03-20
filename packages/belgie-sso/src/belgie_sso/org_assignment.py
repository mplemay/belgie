from __future__ import annotations

from typing import TYPE_CHECKING

from belgie_sso.utils import extract_email_domain

if TYPE_CHECKING:
    from belgie_proto.core.connection import DBConnection
    from belgie_proto.core.user import UserProtocol
    from belgie_proto.organization import OrganizationAdapterProtocol
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.member import MemberProtocol
    from belgie_proto.organization.organization import OrganizationProtocol
    from belgie_proto.sso import SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol


async def provider_matches_verified_domain[
    ProviderT: SSOProviderProtocol,
    DomainT: SSODomainProtocol,
](
    *,
    db: DBConnection,
    adapter: SSOAdapterProtocol[ProviderT, DomainT],
    provider: ProviderT,
    email: str,
) -> bool:
    if not (domain := extract_email_domain(email)):
        return False

    domains = await adapter.list_domains_for_provider(db, sso_provider_id=provider.id)
    return any(item.domain == domain and item.verified_at is not None for item in domains)


async def assign_user_to_provider_organization[
    ProviderT: SSOProviderProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](
    *,
    db: DBConnection,
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT],
    provider: ProviderT,
    user: UserProtocol[str],
) -> bool:
    if await organization_adapter.get_organization_by_id(db, provider.organization_id) is None:
        return False

    if await organization_adapter.get_member(
        db,
        organization_id=provider.organization_id,
        user_id=user.id,
    ):
        return False

    await organization_adapter.create_member(
        db,
        organization_id=provider.organization_id,
        user_id=user.id,
        role="member",
    )
    return True


async def assign_user_by_verified_domain[
    ProviderT: SSOProviderProtocol,
    DomainT: SSODomainProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](
    *,
    db: DBConnection,
    adapter: SSOAdapterProtocol[ProviderT, DomainT],
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT],
    user: UserProtocol[str],
    email: str,
) -> bool:
    if not (domain := extract_email_domain(email)):
        return False

    sso_domain = await adapter.get_verified_domain(db, domain=domain)
    if sso_domain is None:
        return False

    provider = await adapter.get_provider_by_id(db, sso_provider_id=sso_domain.sso_provider_id)
    if provider is None:
        return False

    return await assign_user_to_provider_organization(
        db=db,
        organization_adapter=organization_adapter,
        provider=provider,
        user=user,
    )
