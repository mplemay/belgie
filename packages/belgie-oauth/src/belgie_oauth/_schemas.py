from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Self
from uuid import UUID  # noqa: TC003

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from belgie_oauth._types import RawProfile  # noqa: TC001

if TYPE_CHECKING:
    from belgie_proto.core.individual import IndividualProtocol
    from belgie_proto.core.session import SessionProtocol

    from belgie_oauth._models import OAuthLinkedAccount, OAuthTokenSet, OAuthUserInfo


class OAuthIdTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id_token: str = Field(validation_alias=AliasChoices("id_token", "idToken"))
    nonce: str | None = None
    access_token: str | None = Field(default=None, validation_alias=AliasChoices("access_token", "accessToken"))
    refresh_token: str | None = Field(default=None, validation_alias=AliasChoices("refresh_token", "refreshToken"))
    access_token_expires_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("access_token_expires_at", "accessTokenExpiresAt"),
    )
    refresh_token_expires_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("refresh_token_expires_at", "refreshTokenExpiresAt"),
    )
    token_type: str | None = Field(default=None, validation_alias=AliasChoices("token_type", "tokenType"))
    scope: str | None = None
    scopes: list[str] = Field(default_factory=list)
    request_sign_up: bool = Field(default=False, validation_alias=AliasChoices("request_sign_up", "requestSignUp"))

    @property
    def resolved_scope(self) -> str | None:
        if self.scope is not None:
            return self.scope
        if not self.scopes:
            return None
        return " ".join(dict.fromkeys(self.scopes))


class OAuthProviderAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    provider_account_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("provider_account_id", "providerAccountId"),
    )


class OAuthIndividualResponse(BaseModel):
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    scopes: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_individual(cls, individual: IndividualProtocol[str]) -> Self:
        return cls(
            id=individual.id,
            email=individual.email,
            email_verified=individual.email_verified_at is not None,
            name=individual.name,
            image=individual.image,
            scopes=list(individual.scopes),
            created_at=individual.created_at,
            updated_at=individual.updated_at,
        )


class OAuthSessionSignInResponse(BaseModel):
    redirect: bool = False
    token: str
    individual: OAuthIndividualResponse

    @classmethod
    def from_session(
        cls,
        *,
        individual: IndividualProtocol[str],
        session: SessionProtocol,
    ) -> Self:
        return cls(
            token=str(session.id),
            individual=OAuthIndividualResponse.from_individual(individual),
        )


class OAuthUserInfoResponse(BaseModel):
    provider_account_id: str
    email: str | None
    email_verified: bool
    name: str | None
    image: str | None
    raw: RawProfile

    @classmethod
    def from_user_info(cls, user_info: OAuthUserInfo) -> Self:
        return cls(
            provider_account_id=user_info.provider_account_id,
            email=user_info.email,
            email_verified=user_info.email_verified,
            name=user_info.name,
            image=user_info.image,
            raw=dict(user_info.raw),
        )


class OAuthAccountResponse(BaseModel):
    id: UUID
    individual_id: UUID
    provider: str
    provider_account_id: str
    access_token_expires_at: datetime | None
    refresh_token_expires_at: datetime | None
    token_type: str | None
    scope: str | None
    has_access_token: bool
    has_refresh_token: bool
    has_id_token: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_account(cls, account: OAuthLinkedAccount) -> Self:
        return cls(
            id=account.id,
            individual_id=account.individual_id,
            provider=account.provider,
            provider_account_id=account.provider_account_id,
            access_token_expires_at=account.access_token_expires_at,
            refresh_token_expires_at=account.refresh_token_expires_at,
            token_type=account.token_type,
            scope=account.scope,
            has_access_token=account.access_token is not None,
            has_refresh_token=account.refresh_token is not None,
            has_id_token=account.id_token is not None,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )


class OAuthAccountListResponse(BaseModel):
    accounts: list[OAuthAccountResponse]


class OAuthTokenResponse(BaseModel):
    provider: str
    provider_account_id: str
    access_token: str
    token_type: str | None
    scope: str | None
    access_token_expires_at: datetime | None
    id_token: str | None

    @classmethod
    def from_token_set(cls, *, provider: str, provider_account_id: str, token_set: OAuthTokenSet) -> Self:
        if token_set.access_token is None:
            msg = "token_set is missing access_token"
            raise ValueError(msg)
        return cls(
            provider=provider,
            provider_account_id=provider_account_id,
            access_token=token_set.access_token,
            token_type=token_set.token_type,
            scope=token_set.scope,
            access_token_expires_at=token_set.access_token_expires_at,
            id_token=token_set.id_token,
        )


class OAuthRefreshTokenResponse(OAuthTokenResponse):
    refresh_token: str | None
    refresh_token_expires_at: datetime | None

    @classmethod
    def from_account(cls, account: OAuthLinkedAccount) -> Self:
        if account.access_token is None:
            msg = "account is missing access_token"
            raise ValueError(msg)
        return cls(
            provider=account.provider,
            provider_account_id=account.provider_account_id,
            access_token=account.access_token,
            token_type=account.token_type,
            scope=account.scope,
            access_token_expires_at=account.access_token_expires_at,
            id_token=account.id_token,
            refresh_token=account.refresh_token,
            refresh_token_expires_at=account.refresh_token_expires_at,
        )


class OAuthAccountInfoResponse(BaseModel):
    provider: str
    provider_account_id: str
    user: OAuthUserInfoResponse


class OAuthStatusResponse(BaseModel):
    status: bool
    redirect: bool = False
