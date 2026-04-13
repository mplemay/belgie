from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from belgie_alchemy.__tests__.fixtures.core.models import Session


@pytest.mark.asyncio
async def test_oauth_server_adapter_client_and_state_lifecycle(
    belgie_instance,
    create_individual_session,
    db_session,
    oauth_settings,
) -> None:
    session_uuid = UUID(await create_individual_session(belgie_instance, db_session, "adapter-client@test.com"))
    session = await db_session.scalar(select(Session).where(Session.id == session_uuid))
    assert session is not None

    adapter = oauth_settings.adapter
    client = await adapter.create_client(
        db_session,
        client_id="adapter-client",
        client_secret_hash="secret-hash",
        redirect_uris=["https://client.example/callback"],
        post_logout_redirect_uris=["https://client.example/logout"],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="openid profile",
        client_name="Adapter Client",
        client_uri="https://client.example",
        logo_uri="https://client.example/logo.png",
        contacts=["ops@client.example"],
        tos_uri="https://client.example/tos",
        policy_uri="https://client.example/policy",
        jwks_uri="https://client.example/jwks.json",
        jwks={"keys": []},
        software_id="software-id",
        software_version="1.0.0",
        software_statement="statement",
        type="web",
        subject_type="pairwise",
        require_pkce=True,
        enable_end_session=True,
        client_id_issued_at=123,
        client_secret_expires_at=0,
        individual_id=session.individual_id,
    )

    loaded_client = await adapter.get_client_by_client_id(db_session, client_id=client.client_id)
    assert loaded_client is not None
    assert loaded_client.client_secret_hash == "secret-hash"  # noqa: S105
    assert loaded_client.redirect_uris == ["https://client.example/callback"]
    assert loaded_client.post_logout_redirect_uris == ["https://client.example/logout"]
    assert loaded_client.type == "web"
    assert loaded_client.subject_type == "pairwise"
    assert loaded_client.individual_id == session.individual_id

    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    authorization_state = await adapter.create_authorization_state(
        db_session,
        state="state-123",
        client_id=client.client_id,
        redirect_uri="https://client.example/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge",
        resource="https://api.example",
        scopes=["openid"],
        nonce="nonce-123",
        prompt="login",
        intent="login",
        individual_id=None,
        session_id=None,
        expires_at=expires_at,
    )
    assert authorization_state.client_id == client.client_id
    assert authorization_state.individual_id is None

    bound_state = await adapter.bind_authorization_state(
        db_session,
        state="state-123",
        individual_id=session.individual_id,
        session_id=session.id,
    )
    assert bound_state is not None
    assert bound_state.individual_id == session.individual_id
    assert bound_state.session_id == session.id

    updated_state = await adapter.update_authorization_state_interaction(
        db_session,
        state="state-123",
        prompt="consent",
        intent="consent",
        scopes=["openid", "profile"],
    )
    assert updated_state is not None
    assert updated_state.prompt == "consent"
    assert updated_state.intent == "consent"
    assert updated_state.scopes == ["openid", "profile"]

    assert await adapter.delete_authorization_state(db_session, state="state-123") is True
    assert await adapter.get_authorization_state(db_session, state="state-123") is None


@pytest.mark.asyncio
async def test_oauth_server_adapter_code_and_token_lifecycle(
    belgie_instance,
    create_individual_session,
    db_session,
    oauth_settings,
) -> None:
    session_uuid = UUID(await create_individual_session(belgie_instance, db_session, "adapter-tokens@test.com"))
    session = await db_session.scalar(select(Session).where(Session.id == session_uuid))
    assert session is not None

    adapter = oauth_settings.adapter
    code = await adapter.create_authorization_code(
        db_session,
        code_hash="code-hash",
        client_id=oauth_settings.client_id,
        redirect_uri="https://client.example/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge",
        scopes=["openid", "offline_access"],
        resource="https://api.example",
        nonce="nonce-123",
        individual_id=session.individual_id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    loaded_code = await adapter.get_authorization_code_by_code_hash(db_session, code_hash="code-hash")
    assert loaded_code is not None
    assert loaded_code.id == code.id
    assert loaded_code.scopes == ["openid", "offline_access"]

    refresh_token = await adapter.create_refresh_token(
        db_session,
        token_hash="refresh-hash",
        client_id=oauth_settings.client_id,
        scopes=["openid", "offline_access"],
        resource="https://api.example",
        individual_id=session.individual_id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    loaded_refresh_token = await adapter.get_refresh_token_by_token_hash(db_session, token_hash="refresh-hash")
    assert loaded_refresh_token is not None
    assert loaded_refresh_token.id == refresh_token.id

    access_token = await adapter.create_access_token(
        db_session,
        token_hash="access-hash",
        client_id=oauth_settings.client_id,
        scopes=["openid"],
        resource=["https://api.example", "https://userinfo.example"],
        refresh_token_id=refresh_token.id,
        individual_id=session.individual_id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    loaded_access_token = await adapter.get_access_token_by_token_hash(db_session, token_hash="access-hash")
    assert loaded_access_token is not None
    assert loaded_access_token.id == access_token.id
    assert loaded_access_token.refresh_token_id == refresh_token.id

    revoked_refresh_token = await adapter.update_refresh_token_revoked_at(
        db_session,
        refresh_token_id=refresh_token.id,
        revoked_at=datetime.now(UTC),
    )
    assert revoked_refresh_token is not None
    assert revoked_refresh_token.revoked_at is not None

    assert await adapter.delete_authorization_code_by_code_hash(db_session, code_hash="code-hash") is True
    assert await adapter.delete_access_tokens_by_refresh_token_id(db_session, refresh_token_id=refresh_token.id) == 1
    assert await adapter.delete_refresh_token_by_token_hash(db_session, token_hash="refresh-hash") is True


@pytest.mark.asyncio
async def test_oauth_server_adapter_consent_and_family_cleanup(
    belgie_instance,
    create_individual_session,
    db_session,
    oauth_settings,
) -> None:
    session_uuid = UUID(await create_individual_session(belgie_instance, db_session, "adapter-consent@test.com"))
    session = await db_session.scalar(select(Session).where(Session.id == session_uuid))
    assert session is not None

    adapter = oauth_settings.adapter
    created_consent = await adapter.upsert_consent(
        db_session,
        client_id=oauth_settings.client_id,
        individual_id=session.individual_id,
        scopes=["openid"],
    )
    updated_consent = await adapter.upsert_consent(
        db_session,
        client_id=oauth_settings.client_id,
        individual_id=session.individual_id,
        scopes=["openid", "profile"],
    )
    loaded_consent = await adapter.get_consent(
        db_session,
        client_id=oauth_settings.client_id,
        individual_id=session.individual_id,
    )

    assert created_consent.id == updated_consent.id
    assert loaded_consent is not None
    assert loaded_consent.scopes == ["openid", "profile"]

    first_refresh = await adapter.create_refresh_token(
        db_session,
        token_hash="refresh-family-1",
        client_id=oauth_settings.client_id,
        scopes=["openid"],
        resource="https://api.example",
        individual_id=session.individual_id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    second_refresh = await adapter.create_refresh_token(
        db_session,
        token_hash="refresh-family-2",
        client_id=oauth_settings.client_id,
        scopes=["openid"],
        resource="https://api.example",
        individual_id=session.individual_id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await adapter.create_access_token(
        db_session,
        token_hash="access-family-1",
        client_id=oauth_settings.client_id,
        scopes=["openid"],
        resource="https://api.example",
        refresh_token_id=first_refresh.id,
        individual_id=session.individual_id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await adapter.create_access_token(
        db_session,
        token_hash="access-family-2",
        client_id=oauth_settings.client_id,
        scopes=["openid"],
        resource="https://api.example",
        refresh_token_id=second_refresh.id,
        individual_id=session.individual_id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    assert (
        await adapter.delete_access_tokens_for_client_and_individual(
            db_session,
            client_id=oauth_settings.client_id,
            individual_id=session.individual_id,
        )
        == 2
    )
    assert (
        await adapter.delete_refresh_tokens_for_client_and_individual(
            db_session,
            client_id=oauth_settings.client_id,
            individual_id=session.individual_id,
        )
        == 2
    )
