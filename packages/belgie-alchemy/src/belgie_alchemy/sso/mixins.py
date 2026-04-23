from datetime import datetime
from uuid import UUID

from brussels.types import DateTimeUTC, Json
from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, declared_attr, mapped_column, relationship


@declarative_mixin
class SSOProviderMixin(MappedAsDataclass):
    __tablename__ = "sso_provider"

    @declared_attr
    def organization_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("organization.id", ondelete="cascade", onupdate="cascade"),
            nullable=True,
            default=None,
            kw_only=True,
        )

    @declared_attr
    def created_by_individual_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="cascade", onupdate="cascade"),
            nullable=True,
            default=None,
            kw_only=True,
        )

    @declared_attr
    def provider_type(self) -> Mapped[str]:
        provider_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(provider_type, default="oidc", nullable=False, kw_only=True)

    @declared_attr
    def provider_id(self) -> Mapped[str]:
        provider_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(provider_type, unique=True, index=True, kw_only=True)

    @declared_attr
    def issuer(self) -> Mapped[str]:
        issuer_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(issuer_type, index=True, kw_only=True)

    @declared_attr
    def oidc_config(self) -> Mapped[dict[str, str | bool | list[str] | dict[str, str]] | None]:
        return mapped_column(Json, default=None, nullable=True, kw_only=True)

    @declared_attr
    def saml_config(self) -> Mapped[dict[str, str | bool | list[str] | dict[str, str]] | None]:
        return mapped_column(Json, default=None, nullable=True, kw_only=True)

    @declared_attr
    def domains(self) -> Mapped[list[object]]:
        return relationship(
            "SSODomain",
            back_populates="provider",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[Index, ...]:
        return (
            Index(
                "ix_sso_provider_organization_id",
                self.organization_id,
            ),
            Index(
                "ix_sso_provider_created_by_individual_id",
                self.created_by_individual_id,
            ),
        )


@declarative_mixin
class SSODomainMixin(MappedAsDataclass):
    __tablename__ = "sso_domain"

    @declared_attr
    def sso_provider_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("sso_provider.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def domain(self) -> Mapped[str]:
        domain_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(domain_type, unique=True, index=True, kw_only=True)

    @declared_attr
    def verification_token(self) -> Mapped[str]:
        return mapped_column(Text, kw_only=True)

    @declared_attr
    def verification_token_expires_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def verified_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def provider(self) -> Mapped[object]:
        return relationship(
            "SSOProvider",
            back_populates="domains",
            lazy="selectin",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[Index]:
        return (Index("ix_sso_domain_sso_provider_id", self.sso_provider_id),)


__all__ = [
    "SSODomainMixin",
    "SSOProviderMixin",
]
