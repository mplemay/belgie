from __future__ import annotations

from typing import TYPE_CHECKING

from belgie_sso.utils import choose_best_domain_match, choose_best_verified_domain_match, extract_email_domain


async def provider_matches_domain[ProviderT: SSOProviderProtocol](
    *,
    db: DBConnection,
    adapter: SSOAdapterProtocol[ProviderT],
    provider: ProviderT,
    email: str,
    verified_only: bool,
) -> bool:
    if not (domain := extract_email_domain(email)):
        return False

    domains = await adapter.list_providers_matching_domain(db, domain=domain, verified_only=verified_only)
    try:
        matched_domain = (
            choose_best_verified_domain_match(domain=domain, domains=domains)
            if verified_only
            else choose_best_domain_match(domain=domain, domains=domains)
        )
    except ValueError:
        return False
    return matched_domain is not None and matched_domain.id == provider.id


if TYPE_CHECKING:
    from belgie_proto.core.connection import DBConnection
    from belgie_proto.core.individual import IndividualProtocol
    from belgie_proto.organization import OrganizationAdapterProtocol
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.member import MemberProtocol
    from belgie_proto.organization.organization import OrganizationProtocol
    from belgie_proto.sso import SSOAdapterProtocol, SSOProviderProtocol


async def provider_matches_verified_domain[ProviderT: SSOProviderProtocol](
    *,
    db: DBConnection,
    adapter: SSOAdapterProtocol[ProviderT],
    provider: ProviderT,
    email: str,
) -> bool:
    return await provider_matches_domain(
        db=db,
        adapter=adapter,
        provider=provider,
        email=email,
        verified_only=True,
    )


async def assign_individual_to_provider_organization[
    ProviderT: SSOProviderProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](
    *,
    db: DBConnection,
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT] | None,
    provider: ProviderT,
    individual: IndividualProtocol[str],
    role: str = "member",
) -> bool:
    if organization_adapter is None or provider.organization_id is None:
        return False

    if await organization_adapter.get_organization_by_id(db, provider.organization_id) is None:
        return False

    if await organization_adapter.get_member(
        db,
        organization_id=provider.organization_id,
        individual_id=individual.id,
    ):
        return False

    await organization_adapter.create_member(
        db,
        organization_id=provider.organization_id,
        individual_id=individual.id,
        role=role,
    )
    return True


async def assign_individual_by_domain[  # noqa: PLR0913
    ProviderT: SSOProviderProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](
    *,
    db: DBConnection,
    adapter: SSOAdapterProtocol[ProviderT],
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT] | None,
    individual: IndividualProtocol[str],
    email: str,
    verified_only: bool,
    role: str = "member",
) -> bool:
    if not (domain := extract_email_domain(email)):
        return False

    try:
        provider = (
            choose_best_verified_domain_match(
                domain=domain,
                domains=await adapter.list_providers_matching_domain(db, domain=domain, verified_only=True),
            )
            if verified_only
            else choose_best_domain_match(
                domain=domain,
                domains=await adapter.list_providers_matching_domain(db, domain=domain, verified_only=False),
            )
        )
    except ValueError:
        return False
    if provider is None:
        return False

    return await assign_individual_to_provider_organization(
        db=db,
        organization_adapter=organization_adapter,
        provider=provider,
        individual=individual,
        role=role,
    )


async def assign_individual_by_verified_domain[  # noqa: PLR0913
    ProviderT: SSOProviderProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](
    *,
    db: DBConnection,
    adapter: SSOAdapterProtocol[ProviderT],
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT] | None,
    individual: IndividualProtocol[str],
    email: str,
    role: str = "member",
) -> bool:
    return await assign_individual_by_domain(
        db=db,
        adapter=adapter,
        organization_adapter=organization_adapter,
        individual=individual,
        email=email,
        verified_only=True,
        role=role,
    )
