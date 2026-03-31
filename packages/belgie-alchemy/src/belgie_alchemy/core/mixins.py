from __future__ import annotations

import sys
from datetime import datetime  # noqa: TC003
from typing import Final
from uuid import UUID

from belgie_proto.core.customer import CustomerType
from brussels.types import DateTimeUTC
from sqlalchemy import JSON, Enum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, declared_attr, mapped_column, relationship

CustomerEnum: Final[Enum] = Enum(CustomerType, name="customer_type", native_enum=False)

if sys.version_info >= (3, 14):
    from uuid import uuid7 as _customer_pk_uuid
else:
    from uuid import uuid4 as _customer_pk_uuid


@declarative_mixin
class CustomerMixin(MappedAsDataclass):
    __tablename__ = "customer"

    @declared_attr
    def customer_type(self) -> Mapped[CustomerType]:
        return mapped_column(CustomerEnum, index=True, init=False)

    @declared_attr
    def name(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr.directive
    def __mapper_args__(self) -> dict[str, object]:
        return {
            "polymorphic_on": self.customer_type,
            "polymorphic_abstract": True,
            "with_polymorphic": "*",
        }


@declarative_mixin
class IndividualMixin(MappedAsDataclass):
    __tablename__ = "individual"

    @declared_attr
    def id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("customer.id", ondelete="cascade", onupdate="cascade"),
            primary_key=True,
            default_factory=_customer_pk_uuid,
            insert_default=_customer_pk_uuid,
            init=False,
        )

    @declared_attr
    def email(self) -> Mapped[str]:
        email_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(email_type, unique=True, index=True, kw_only=True)

    @declared_attr
    def email_verified_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def image(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def scopes(self) -> Mapped[list[str]]:
        scopes_type = JSON().with_variant(ARRAY(Text()), "postgresql")
        return mapped_column(scopes_type, default_factory=list, nullable=False, kw_only=True)

    @declared_attr
    def accounts(self) -> Mapped[list[object]]:
        return relationship(
            "Account",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr
    def sessions(self) -> Mapped[list[object]]:
        return relationship(
            "Session",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr
    def oauth_states(self) -> Mapped[list[object]]:
        return relationship(
            "OAuthState",
            back_populates="individual",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr.directive
    def __mapper_args__(self) -> dict[str, object]:
        return {"polymorphic_identity": CustomerType.INDIVIDUAL}


@declarative_mixin
class AccountMixin(MappedAsDataclass):
    __tablename__ = "account"

    @declared_attr
    def individual_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def provider(self) -> Mapped[str]:
        provider_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(provider_type, kw_only=True)

    @declared_attr
    def provider_account_id(self) -> Mapped[str]:
        return mapped_column(Text(), kw_only=True)

    @declared_attr
    def access_token(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def refresh_token(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def expires_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def token_type(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def scope(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def id_token(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def individual(self) -> Mapped[object]:
        return relationship(
            "Individual",
            back_populates="accounts",
            lazy="selectin",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[UniqueConstraint, Index]:
        return (
            UniqueConstraint(
                self.provider,
                self.provider_account_id,
                name="uq_accounts_provider_provider_account_id",
            ),
            Index(
                f"ix_{self.__tablename__}_individual_id_provider",
                self.individual_id,
                self.provider,
            ),
        )


@declarative_mixin
class SessionMixin(MappedAsDataclass):
    __tablename__ = "session"

    @declared_attr
    def individual_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="cascade", onupdate="cascade"),
            index=True,
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, index=True, kw_only=True)

    @declared_attr
    def ip_address(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def user_agent(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def individual(self) -> Mapped[object]:
        return relationship(
            "Individual",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )


@declarative_mixin
class OAuthStateMixin(MappedAsDataclass):
    __tablename__ = "oauth_state"

    @declared_attr
    def state(self) -> Mapped[str]:
        return mapped_column(Text, unique=True, index=True, kw_only=True)

    @declared_attr
    def individual_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, kw_only=True)

    @declared_attr
    def code_verifier(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def redirect_url(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def individual(self) -> Mapped[object | None]:
        return relationship(
            "Individual",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )


__all__ = [
    "AccountMixin",
    "CustomerMixin",
    "IndividualMixin",
    "OAuthStateMixin",
    "SessionMixin",
]
