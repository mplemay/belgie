from __future__ import annotations

from typing import TYPE_CHECKING, Any

from belgie_sso.utils import domain_matches, extract_email_domain

if TYPE_CHECKING:
    from belgie_proto.core.connection import DBConnection
    from belgie_proto.core.individual import IndividualProtocol
    from belgie_proto.organization import OrganizationAdapterProtocol
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.member import MemberProtocol
    from belgie_proto.organization.organization import OrganizationProtocol
    from belgie_proto.sso import SSOAdapterProtocol, SSODomainProtocol, SSOProviderProtocol

    from belgie_sso.settings import OrganizationProvisioningOptions


async def _resolve_role[  # noqa: PLR0913
    ProviderT: SSOProviderProtocol,
](
    *,
    provisioning_options: OrganizationProvisioningOptions | None,
    individual: IndividualProtocol[str],
    provider: ProviderT,
    email: str | None = None,
    user_info: dict[str, Any] | None = None,
    token: Any = None,  # noqa: ANN401
) -> str:
    if provisioning_options is None:
        return "member"
    if provisioning_options.get_role is None:
        return provisioning_options.default_role

    role = await provisioning_options.get_role(
        individual=individual,
        provider=provider,
        email=email,
        user_info=user_info or {},
        token=token,
    )
    if role not in {"member", "admin"}:
        msg = "organization provisioning get_role must return 'member' or 'admin'"
        raise ValueError(msg)
    return role


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
    return any(item.verified_at is not None and domain_matches(domain, item.domain) for item in domains)


async def assign_individual_to_provider_organization[  # noqa: PLR0913
    ProviderT: SSOProviderProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](
    *,
    db: DBConnection,
    organization_adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT],
    provider: ProviderT,
    individual: IndividualProtocol[str],
    provisioning_options: OrganizationProvisioningOptions | None = None,
    email: str | None = None,
    user_info: dict[str, Any] | None = None,
    token: Any = None,  # noqa: ANN401
) -> bool:
    if provisioning_options is not None and provisioning_options.disabled:
        return False

    if await organization_adapter.get_organization_by_id(db, provider.organization_id) is None:
        return False

    if await organization_adapter.get_member(
        db,
        organization_id=provider.organization_id,
        individual_id=individual.id,
    ):
        return False

    role = await _resolve_role(
        provisioning_options=provisioning_options,
        individual=individual,
        provider=provider,
        email=email,
        user_info=user_info,
        token=token,
    )
    await organization_adapter.create_member(
        db,
        organization_id=provider.organization_id,
        individual_id=individual.id,
        role=role,
    )
    return True


async def assign_individual_by_verified_domain[  # noqa: PLR0913
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
    individual: IndividualProtocol[str],
    email: str,
    provisioning_options: OrganizationProvisioningOptions | None = None,
) -> bool:
    if not (domain := extract_email_domain(email)):
        return False

    sso_domain = await adapter.get_best_verified_domain(db, domain=domain)
    if sso_domain is None:
        return False

    provider = await adapter.get_provider_by_id(db, sso_provider_id=sso_domain.sso_provider_id)
    if provider is None:
        return False

    return await assign_individual_to_provider_organization(
        db=db,
        organization_adapter=organization_adapter,
        provider=provider,
        individual=individual,
        provisioning_options=provisioning_options,
        email=email,
    )
