from __future__ import annotations

from brussels.types import DateTimeUTC
from sqlalchemy import JSON, Enum as SAEnum, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, dialect as postgresql_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from belgie_alchemy.__tests__.fixtures.core.models import (
    OAuthServerAccessToken,
    OAuthServerAuthorizationCode,
    OAuthServerAuthorizationState,
    OAuthServerClient,
    OAuthServerConsent,
    OAuthServerRefreshToken,
)
from belgie_alchemy.oauth_server import (
    OAuthServerAccessTokenMixin,
    OAuthServerAuthorizationCodeMixin,
    OAuthServerAuthorizationStateMixin,
    OAuthServerClientMixin,
    OAuthServerConsentMixin,
    OAuthServerRefreshTokenMixin,
)


def test_oauth_server_mixins_exported() -> None:
    assert OAuthServerClientMixin is not None
    assert OAuthServerAuthorizationStateMixin is not None
    assert OAuthServerAuthorizationCodeMixin is not None
    assert OAuthServerAccessTokenMixin is not None
    assert OAuthServerRefreshTokenMixin is not None
    assert OAuthServerConsentMixin is not None


def test_fixture_models_use_oauth_server_mixins() -> None:
    assert issubclass(OAuthServerClient, OAuthServerClientMixin)
    assert issubclass(OAuthServerAuthorizationState, OAuthServerAuthorizationStateMixin)
    assert issubclass(OAuthServerAuthorizationCode, OAuthServerAuthorizationCodeMixin)
    assert issubclass(OAuthServerAccessToken, OAuthServerAccessTokenMixin)
    assert issubclass(OAuthServerRefreshToken, OAuthServerRefreshTokenMixin)
    assert issubclass(OAuthServerConsent, OAuthServerConsentMixin)


def test_oauth_server_mixin_default_tablenames() -> None:
    assert OAuthServerClientMixin.__tablename__ == "oauth_client"
    assert OAuthServerAuthorizationStateMixin.__tablename__ == "oauth_authorization_state"
    assert OAuthServerAuthorizationCodeMixin.__tablename__ == "oauth_authorization_code"
    assert OAuthServerAccessTokenMixin.__tablename__ == "oauth_access_token"
    assert OAuthServerRefreshTokenMixin.__tablename__ == "oauth_refresh_token"
    assert OAuthServerConsentMixin.__tablename__ == "oauth_consent"


def test_oauth_client_mixin_columns_and_types() -> None:
    postgres = postgresql_dialect()
    sqlite = sqlite_dialect()

    client_id_column = OAuthServerClient.__table__.c.client_id
    assert client_id_column.unique
    assert client_id_column.index

    redirect_uris_column = OAuthServerClient.__table__.c.redirect_uris
    assert isinstance(redirect_uris_column.type.dialect_impl(postgres), PG_ARRAY)
    assert isinstance(redirect_uris_column.type.dialect_impl(postgres).item_type, Text)
    assert isinstance(redirect_uris_column.type.dialect_impl(sqlite), type(JSON().dialect_impl(sqlite)))
    assert redirect_uris_column.nullable
    assert redirect_uris_column.default is None

    post_logout_redirect_uris_column = OAuthServerClient.__table__.c.post_logout_redirect_uris
    assert isinstance(post_logout_redirect_uris_column.type.dialect_impl(postgres), PG_ARRAY)
    assert post_logout_redirect_uris_column.nullable
    assert post_logout_redirect_uris_column.default is None

    contacts_column = OAuthServerClient.__table__.c.contacts
    assert isinstance(contacts_column.type.dialect_impl(postgres), PG_ARRAY)
    assert contacts_column.nullable

    individual_id_fk = next(iter(OAuthServerClient.__table__.c.individual_id.foreign_keys))
    assert individual_id_fk.target_fullname == "individual.id"
    assert individual_id_fk.ondelete == "set null"
    assert individual_id_fk.onupdate == "cascade"


def test_oauth_authorization_state_mixin_defaults() -> None:
    state_column = OAuthServerAuthorizationState.__table__.c.state
    assert state_column.unique
    assert state_column.index

    client_id_column = OAuthServerAuthorizationState.__table__.c.client_id
    assert client_id_column.index
    assert len(client_id_column.foreign_keys) == 0

    intent_column = OAuthServerAuthorizationState.__table__.c.intent
    assert isinstance(intent_column.type, SAEnum)
    assert intent_column.type.native_enum is False
    assert tuple(intent_column.type.enums) == ("login", "create", "consent", "select_account")

    expires_at_column = OAuthServerAuthorizationState.__table__.c.expires_at
    assert isinstance(expires_at_column.type, DateTimeUTC)
    assert expires_at_column.index

    individual_id_fk = next(iter(OAuthServerAuthorizationState.__table__.c.individual_id.foreign_keys))
    assert individual_id_fk.target_fullname == "individual.id"
    assert individual_id_fk.ondelete == "set null"
    assert individual_id_fk.onupdate == "cascade"

    session_id_fk = next(iter(OAuthServerAuthorizationState.__table__.c.session_id.foreign_keys))
    assert session_id_fk.target_fullname == "session.id"
    assert session_id_fk.ondelete == "set null"
    assert session_id_fk.onupdate == "cascade"


def test_oauth_authorization_code_mixin_defaults() -> None:
    postgres = postgresql_dialect()
    sqlite = sqlite_dialect()

    code_hash_column = OAuthServerAuthorizationCode.__table__.c.code_hash
    assert code_hash_column.unique
    assert code_hash_column.index

    client_id_column = OAuthServerAuthorizationCode.__table__.c.client_id
    assert client_id_column.index
    assert len(client_id_column.foreign_keys) == 0

    scopes_column = OAuthServerAuthorizationCode.__table__.c.scopes
    assert isinstance(scopes_column.type.dialect_impl(postgres), PG_ARRAY)
    assert isinstance(scopes_column.type.dialect_impl(sqlite), type(JSON().dialect_impl(sqlite)))
    assert not scopes_column.nullable

    expires_at_column = OAuthServerAuthorizationCode.__table__.c.expires_at
    assert isinstance(expires_at_column.type, DateTimeUTC)
    assert expires_at_column.index


def test_oauth_token_and_consent_mixins_defaults() -> None:
    access_token_client_index = next(
        index
        for index in OAuthServerAccessToken.__table__.indexes
        if index.name == "ix_oauth_access_token_client_id_individual_id"
    )
    assert isinstance(access_token_client_index, Index)
    assert tuple(access_token_client_index.columns) == (
        OAuthServerAccessToken.__table__.c.client_id,
        OAuthServerAccessToken.__table__.c.individual_id,
    )

    access_token_refresh_index = next(
        index
        for index in OAuthServerAccessToken.__table__.indexes
        if index.name == "ix_oauth_access_token_refresh_token_id"
    )
    assert isinstance(access_token_refresh_index, Index)
    assert tuple(access_token_refresh_index.columns) == (OAuthServerAccessToken.__table__.c.refresh_token_id,)

    refresh_token_fk = next(iter(OAuthServerAccessToken.__table__.c.refresh_token_id.foreign_keys))
    assert refresh_token_fk.target_fullname == "oauth_refresh_token.id"
    assert refresh_token_fk.ondelete == "set null"
    assert refresh_token_fk.onupdate == "cascade"

    refresh_token_client_index = next(
        index
        for index in OAuthServerRefreshToken.__table__.indexes
        if index.name == "ix_oauth_refresh_token_client_id_individual_id"
    )
    assert isinstance(refresh_token_client_index, Index)
    assert tuple(refresh_token_client_index.columns) == (
        OAuthServerRefreshToken.__table__.c.client_id,
        OAuthServerRefreshToken.__table__.c.individual_id,
    )

    revoked_at_column = OAuthServerRefreshToken.__table__.c.revoked_at
    assert isinstance(revoked_at_column.type, DateTimeUTC)
    assert revoked_at_column.nullable

    consent_client_id_column = OAuthServerConsent.__table__.c.client_id
    assert consent_client_id_column.index
    assert len(consent_client_id_column.foreign_keys) == 0

    consent_individual_id_fk = next(iter(OAuthServerConsent.__table__.c.individual_id.foreign_keys))
    assert consent_individual_id_fk.target_fullname == "individual.id"
    assert consent_individual_id_fk.ondelete == "cascade"
    assert consent_individual_id_fk.onupdate == "cascade"

    consent_constraint = next(
        constraint
        for constraint in OAuthServerConsent.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_oauth_consent_client_id_individual_id_reference_id"
    )
    assert tuple(consent_constraint.columns) == (
        OAuthServerConsent.__table__.c.client_id,
        OAuthServerConsent.__table__.c.individual_id,
        OAuthServerConsent.__table__.c.reference_id,
    )
