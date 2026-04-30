from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import isawaitable
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import UUID

from authlib.oauth2.rfc7591.claims import ClientMetadataClaims as OAuth2ClientMetadataClaims
from authlib.oidc.registration.claims import ClientMetadataClaims as OIDCClientMetadataClaims
from authlib.oidc.rpinitiated.registration import ClientMetadataClaims as RPInitiatedClientMetadataClaims
from belgie_proto.core.connection import DBConnection
from joserfc.errors import InvalidClaimError, JoseError
from pydantic import AnyUrl

from belgie_oauth_server.metadata import build_oauth_metadata, build_openid_metadata
from belgie_oauth_server.models import (
    OAuthServerAdminClientMetadata,
    OAuthServerClientInformationFull,
    OAuthServerClientMetadata,
    OAuthServerToken,
)
from belgie_oauth_server.signing import OAuthServerSigningState, build_signing_state
from belgie_oauth_server.utils import construct_redirect_uri, dedupe_scopes, parse_scope_string

if TYPE_CHECKING:
    from belgie_proto.oauth_server import (
        OAuthServerAccessTokenProtocol,
        OAuthServerAuthorizationCodeProtocol,
        OAuthServerAuthorizationStateProtocol,
        OAuthServerClientProtocol,
        OAuthServerConsentProtocol,
        OAuthServerRefreshTokenProtocol,
    )
    from belgie_proto.oauth_server.types import AuthorizationIntent, OAuthServerAudience

    from belgie_oauth_server.settings import OAuthServer

_RESERVED_ACCESS_TOKEN_CLAIMS = frozenset({"iss", "sub", "aud", "azp", "scope", "iat", "exp", "sid"})
_UNSET = object()
_TIME_SPAN_UNITS = {
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "s": 1,
    "minute": 60,
    "minutes": 60,
    "min": 60,
    "mins": 60,
    "m": 60,
    "hour": 3600,
    "hours": 3600,
    "hr": 3600,
    "hrs": 3600,
    "h": 3600,
    "day": 86400,
    "days": 86400,
    "d": 86400,
    "week": 604800,
    "weeks": 604800,
    "w": 604800,
    "year": 31557600,
    "years": 31557600,
    "yr": 31557600,
    "yrs": 31557600,
    "y": 31557600,
}
JWT_DELIMITER_COUNT = 2
_TIME_SPAN_PATTERN = re.compile(r"^(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]+)$")


def _resolve_time_span_to_timestamp(value: str) -> int:
    normalized = value.strip().lower()
    direction = 1
    if normalized.endswith("from now"):
        normalized = normalized.removesuffix("from now").strip()
    elif normalized.endswith("ago"):
        normalized = normalized.removesuffix("ago").strip()
        direction = -1
    if normalized.startswith("-"):
        normalized = normalized[1:].strip()
        direction = -1

    match = _TIME_SPAN_PATTERN.fullmatch(normalized)
    if match is None:
        msg = "invalid client_secret_expires_at"
        raise ValueError(msg)

    unit = match.group("unit")
    seconds_per_unit = _TIME_SPAN_UNITS.get(unit)
    if seconds_per_unit is None:
        msg = "invalid client_secret_expires_at"
        raise ValueError(msg)

    amount = float(match.group("value"))
    return int(time.time() + (direction * amount * seconds_per_unit))


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationParams:
    state: str | None
    scopes: list[str] | None
    code_challenge: str | None
    code_challenge_method: str | None = None
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None
    nonce: str | None = None
    prompt: str | None = None
    intent: AuthorizationIntent = "login"
    individual_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationCode:
    code: str
    scopes: list[str]
    expires_at: float
    client_id: str
    code_challenge: str | None
    redirect_uri: AnyUrl
    redirect_uri_provided_explicitly: bool
    resource: str | None = None
    nonce: str | None = None
    individual_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshToken:
    id: UUID | None = None
    token: str
    client_id: str
    scopes: list[str]
    created_at: int
    expires_at: int | None = None
    revoked_at: int | None = None
    individual_id: str | None = None
    session_id: str | None = None
    resource: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessToken:
    token: str
    client_id: str
    scopes: list[str]
    created_at: int
    expires_at: int | None = None
    resource: OAuthServerAudience | None = None
    refresh_token: str | None = None
    individual_id: str | None = None
    session_id: str | None = None
    claims: dict[str, object] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StateEntry:
    state: str
    client_state: str | None
    redirect_uri: str
    code_challenge: str | None
    redirect_uri_provided_explicitly: bool
    client_id: str
    resource: str | None
    scopes: list[str] | None
    created_at: float
    nonce: str | None = None
    prompt: str | None = None
    intent: AuthorizationIntent = "login"
    individual_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsentEntry:
    id: UUID
    client_id: str
    individual_id: str
    reference_id: str | None
    scopes: list[str]
    created_at: int


class SimpleOAuthProvider:
    _NON_EXPIRING_STATE_EXPIRES_AT = datetime.max.replace(tzinfo=UTC)

    def __init__(
        self,
        settings: OAuthServer,
        issuer_url: str,
        *,
        database_factory: Callable[[], DBConnection | AsyncGenerator[DBConnection, None]] | None = None,
        fallback_signing_secret: str | None = None,
    ) -> None:
        self.settings = settings
        self.issuer_url = issuer_url
        self.adapter = settings.adapter
        self.database_factory = database_factory

        fb = (
            settings.fallback_signing_secret.get_secret_value()
            if settings.fallback_signing_secret is not None
            else None
        )
        self.fallback_signing_secret = fallback_signing_secret or fb or ""
        self.signing_state: OAuthServerSigningState = build_signing_state(
            settings.signing,
            self.fallback_signing_secret,
        )

    async def _apply_trusted_client_policy(
        self,
        oauth_client: OAuthServerClientInformationFull,
    ) -> OAuthServerClientInformationFull:
        if oauth_client.skip_consent:
            return oauth_client
        if not await self.settings.is_trusted_client(oauth_client):
            return oauth_client
        return oauth_client.model_copy(update={"skip_consent": True})

    async def get_client(
        self,
        client_id: str,
        *,
        db: DBConnection | None = None,
    ) -> OAuthServerClientInformationFull | None:
        async with self._db_session(db) as session:
            if (client := await self.adapter.get_client_by_client_id(session, client_id=client_id)) is None:
                return None
            return await self._apply_trusted_client_policy(self._client_information_from_record(client))

    async def list_clients(
        self,
        *,
        individual_id: str | None = None,
        reference_id: str | None = None,
        db: DBConnection | None = None,
    ) -> list[OAuthServerClientInformationFull]:
        async with self._db_session(db) as session:
            clients = await self.adapter.list_clients(
                session,
                individual_id=self._parse_uuid(individual_id),
                reference_id=reference_id,
            )
        return [
            await self._apply_trusted_client_policy(self._client_information_from_record(client)) for client in clients
        ]

    async def update_client(
        self,
        client_id: str,
        *,
        updates: dict[str, object],
        db: DBConnection | None = None,
    ) -> OAuthServerClientInformationFull | None:
        if client_id in self.settings.cached_trusted_clients:
            msg = "trusted clients must be updated manually"
            raise ValueError(msg)
        async with self._db_session(db, transactional=True) as session:
            existing_client = await self.adapter.get_client_by_client_id(session, client_id=client_id)
            if existing_client is None:
                return None

            normalized_updates = dict(updates)
            if "client_secret_expires_at" in normalized_updates:
                normalized_updates["client_secret_expires_at"] = self._resolve_client_secret_expiration(
                    normalized_updates["client_secret_expires_at"],
                )

            updated_auth_method = normalized_updates.get(
                "token_endpoint_auth_method",
                existing_client.token_endpoint_auth_method,
            )
            if (
                updated_auth_method in {"client_secret_post", "client_secret_basic"}
                and existing_client.client_secret_hash is None
            ):
                msg = "confidential clients require a stored client secret"
                raise ValueError(msg)

            client = await self.adapter.update_client(session, client_id=client_id, updates=normalized_updates)
            if client is None:
                return None
            return await self._apply_trusted_client_policy(self._client_information_from_record(client))

    async def delete_client(
        self,
        client_id: str,
        *,
        db: DBConnection | None = None,
    ) -> bool:
        if client_id in self.settings.cached_trusted_clients:
            msg = "trusted clients must be updated manually"
            raise ValueError(msg)
        async with self._db_session(db, transactional=True) as session:
            return await self.adapter.delete_client(session, client_id=client_id)

    async def rotate_client_secret(
        self,
        client_id: str,
        *,
        db: DBConnection | None = None,
    ) -> OAuthServerClientInformationFull | None:
        if client_id in self.settings.cached_trusted_clients:
            msg = "trusted clients must be updated manually"
            raise ValueError(msg)
        async with self._db_session(db, transactional=True) as session:
            client = await self.adapter.get_client_by_client_id(session, client_id=client_id)
            if client is None:
                return None
            if client.token_endpoint_auth_method == "none":  # noqa: S105
                msg = "public clients cannot rotate secrets"
                raise ValueError(msg)

            raw_client_secret = await self._generate_client_secret()
            stored_client_secret, client_secret_hash = self._store_client_secret(raw_client_secret)
            rotated = await self.adapter.update_client(
                session,
                client_id=client_id,
                updates={
                    "client_secret": stored_client_secret,
                    "client_secret_hash": client_secret_hash,
                    "client_secret_expires_at": self._resolve_client_secret_expiration(),
                },
            )
            if rotated is None:
                return None
            info = self._client_information_from_record(rotated)
            info.client_secret = self._prefix_client_secret(raw_client_secret)
            return await self._apply_trusted_client_policy(info)

    async def authenticate_client(  # noqa: PLR0911
        self,
        client_id: str,
        client_secret: str | None,
        *,
        require_credentials: bool = False,
        require_confidential: bool = False,
        db: DBConnection | None = None,
    ) -> OAuthServerClientInformationFull | None:
        normalized_client_secret = self._normalize_supplied_client_secret(client_secret)

        async with self._db_session(db) as session:
            client = await self.adapter.get_client_by_client_id(session, client_id=client_id)
            if client is None:
                return None

            oauth_client = await self._apply_trusted_client_policy(self._client_information_from_record(client))
            if oauth_client.disabled:
                return None
            if oauth_client.token_endpoint_auth_method == "none":  # noqa: S105
                if require_credentials or require_confidential or normalized_client_secret:
                    return None
                return oauth_client

            if not normalized_client_secret or client.client_secret_hash is None:
                return None

            if not hmac.compare_digest(self._hash_value(normalized_client_secret), client.client_secret_hash):
                return None
            return oauth_client

    async def register_client(
        self,
        metadata: OAuthServerClientMetadata | OAuthServerAdminClientMetadata,
        *,
        individual_id: str | None = None,
        reference_id: str | None = None,
        allow_confidential_pkce_opt_out: bool = False,
        db: DBConnection | None = None,
    ) -> OAuthServerClientInformationFull:
        token_endpoint_auth_method = metadata.token_endpoint_auth_method or "client_secret_basic"
        if token_endpoint_auth_method not in {"client_secret_post", "client_secret_basic", "none"}:
            msg = f"unsupported token_endpoint_auth_method: {token_endpoint_auth_method}"
            raise ValueError(msg)

        require_pkce = True if metadata.require_pkce is None else metadata.require_pkce
        if token_endpoint_auth_method == "none":  # noqa: S105
            require_pkce = True
        elif require_pkce is not True and not allow_confidential_pkce_opt_out:
            msg = "pkce is required for registered clients"
            raise ValueError(msg)

        raw_client_secret = None
        client_secret = None
        client_secret_hash = None
        client_secret_expires_at = self._resolve_client_secret_expiration(
            getattr(metadata, "client_secret_expires_at", _UNSET),
        )
        enable_end_session = getattr(metadata, "enable_end_session", None)
        skip_consent = bool(metadata.skip_consent)
        if token_endpoint_auth_method != "none":  # noqa: S105
            raw_client_secret = await self._generate_client_secret()
            client_secret, client_secret_hash = self._store_client_secret(raw_client_secret)

        issued_at = int(time.time())
        async with self._db_session(db, transactional=True) as session:
            client_id = await self._generate_client_id()
            while (await self.adapter.get_client_by_client_id(session, client_id=client_id)) is not None:
                client_id = await self._generate_client_id()

            client = await self.adapter.create_client(
                session,
                client_id=client_id,
                client_secret=client_secret,
                client_secret_hash=client_secret_hash,
                disabled=metadata.disabled,
                skip_consent=skip_consent,
                redirect_uris=(
                    [str(uri) for uri in metadata.redirect_uris] if metadata.redirect_uris is not None else None
                ),
                post_logout_redirect_uris=(
                    [str(uri) for uri in metadata.post_logout_redirect_uris]
                    if metadata.post_logout_redirect_uris is not None
                    else None
                ),
                token_endpoint_auth_method=token_endpoint_auth_method,
                grant_types=list(metadata.grant_types),
                response_types=list(metadata.response_types),
                scope=metadata.scope
                or " ".join(self.settings.client_registration_default_scopes or self.settings.default_scopes),
                client_name=metadata.client_name,
                client_uri=str(metadata.client_uri) if metadata.client_uri is not None else None,
                logo_uri=str(metadata.logo_uri) if metadata.logo_uri is not None else None,
                contacts=list(metadata.contacts) if metadata.contacts is not None else None,
                tos_uri=str(metadata.tos_uri) if metadata.tos_uri is not None else None,
                policy_uri=str(metadata.policy_uri) if metadata.policy_uri is not None else None,
                software_id=metadata.software_id,
                software_version=metadata.software_version,
                software_statement=metadata.software_statement,
                type=metadata.type,
                subject_type=metadata.subject_type,
                require_pkce=require_pkce,
                enable_end_session=enable_end_session,
                reference_id=reference_id or metadata.reference_id,
                metadata_json=metadata.metadata_json,
                client_id_issued_at=issued_at,
                client_secret_expires_at=client_secret_expires_at,
                individual_id=self._parse_uuid(individual_id),
            )
            client_info = self._client_information_from_record(client)
            if raw_client_secret is not None:
                client_info.client_secret = self._prefix_client_secret(raw_client_secret)
            return client_info

    async def authorize(
        self,
        client: OAuthServerClientInformationFull,
        params: AuthorizationParams,
        *,
        db: DBConnection | None = None,
    ) -> str:
        client_state = params.state or None
        state = params.state or secrets.token_hex(16)
        async with self._db_session(db, transactional=True) as session:
            while (existing_state := await self.adapter.get_authorization_state(session, state=state)) is not None:
                if self._is_expired(existing_state.expires_at):
                    await self.adapter.delete_authorization_state(session, state=state)
                    break
                state = secrets.token_hex(16)

            await self.adapter.create_authorization_state(
                session,
                state=state,
                client_state=client_state,
                client_id=client.client_id,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                code_challenge=params.code_challenge,
                resource=params.resource,
                scopes=list(params.scopes) if params.scopes is not None else None,
                nonce=params.nonce,
                prompt=params.prompt,
                intent=params.intent,
                individual_id=self._parse_uuid(params.individual_id),
                session_id=self._parse_uuid(params.session_id),
                expires_at=self._state_expires_at(self.settings.state_ttl_seconds),
            )
        return state

    async def bind_authorization_state(
        self,
        state: str,
        *,
        individual_id: str,
        session_id: str,
        db: DBConnection | None = None,
    ) -> None:
        async with self._db_session(db, transactional=True) as session:
            state_record = await self.adapter.get_authorization_state(session, state=state)
            if state_record is None or await self._delete_expired_state_if_needed(session, state_record):
                msg = "Invalid state parameter"
                raise ValueError(msg)

            bound_state = await self.adapter.bind_authorization_state(
                session,
                state=state,
                individual_id=self._require_uuid(individual_id),
                session_id=self._require_uuid(session_id),
            )
            if bound_state is None:
                msg = "Invalid state parameter"
                raise ValueError(msg)

    async def update_authorization_interaction(
        self,
        state: str,
        *,
        prompt: str | None,
        intent: AuthorizationIntent,
        scopes: list[str] | None = None,
        db: DBConnection | None = None,
    ) -> None:
        async with self._db_session(db, transactional=True) as session:
            state_record = await self.adapter.get_authorization_state(session, state=state)
            if state_record is None or await self._delete_expired_state_if_needed(session, state_record):
                msg = "Invalid state parameter"
                raise ValueError(msg)

            updated_state = await self.adapter.update_authorization_state_interaction(
                session,
                state=state,
                prompt=prompt,
                intent=intent,
                scopes=list(scopes) if scopes is not None else None,
            )
            if updated_state is None:
                msg = "Invalid state parameter"
                raise ValueError(msg)

    async def load_authorization_state(
        self,
        state: str,
        *,
        db: DBConnection | None = None,
    ) -> StateEntry | None:
        async with self._db_session(db, transactional=True) as session:
            state_record = await self.adapter.get_authorization_state(session, state=state)
            if state_record is None:
                return None
            if await self._delete_expired_state_if_needed(session, state_record):
                return None
            return self._state_entry_from_record(state_record)

    async def issue_authorization_code(
        self,
        state: str,
        *,
        issuer: str | None = None,
        db: DBConnection | None = None,
    ) -> str:
        async with self._db_session(db, transactional=True) as session:
            state_record = await self.adapter.get_authorization_state(session, state=state)
            if state_record is None or await self._delete_expired_state_if_needed(session, state_record):
                msg = "Invalid state parameter"
                raise ValueError(msg)

            scopes = (
                list(state_record.scopes) if state_record.scopes is not None else list(self.settings.default_scopes)
            )
            new_code = f"belgie_{secrets.token_hex(16)}"
            redirect_uri = state_record.redirect_uri
            await self.adapter.create_authorization_code(
                session,
                code_hash=self._hash_value(new_code),
                client_id=state_record.client_id,
                redirect_uri=state_record.redirect_uri,
                redirect_uri_provided_explicitly=state_record.redirect_uri_provided_explicitly,
                code_challenge=state_record.code_challenge,
                scopes=scopes,
                resource=state_record.resource,
                nonce=state_record.nonce,
                individual_id=state_record.individual_id,
                session_id=state_record.session_id,
                expires_at=self._expires_at(self.settings.authorization_code_ttl_seconds),
            )
            await self.adapter.delete_authorization_state(session, state=state)

        client_state = getattr(state_record, "client_state", state)
        return construct_redirect_uri(redirect_uri, code=new_code, state=client_state, iss=issuer)

    async def load_authorization_code(
        self,
        authorization_code: str,
        *,
        db: DBConnection | None = None,
    ) -> AuthorizationCode | None:
        async with self._db_session(db, transactional=True) as session:
            code_record = await self.adapter.get_authorization_code_by_code_hash(
                session,
                code_hash=self._hash_value(authorization_code),
            )
            if code_record is None:
                return None
            if await self._delete_expired_authorization_code_if_needed(session, code_record):
                return None
            return self._authorization_code_from_record(authorization_code, code_record)

    async def delete_authorization_code(
        self,
        authorization_code: AuthorizationCode | str,
        *,
        db: DBConnection | None = None,
    ) -> None:
        code_value = (
            authorization_code.code if isinstance(authorization_code, AuthorizationCode) else authorization_code
        )
        async with self._db_session(db, transactional=True) as session:
            await self.adapter.delete_authorization_code_by_code_hash(
                session,
                code_hash=self._hash_value(code_value),
            )

    async def exchange_authorization_code(
        self,
        authorization_code: AuthorizationCode,
        *,
        issue_refresh_token: bool = False,
        access_token_resource: OAuthServerAudience | None = None,
        db: DBConnection | None = None,
    ) -> OAuthServerToken:
        code_hash = self._hash_value(authorization_code.code)
        async with self._db_session(db, transactional=True) as session:
            code_record = await self.adapter.get_authorization_code_by_code_hash(session, code_hash=code_hash)
            if code_record is None:
                msg = "Invalid authorization code"
                raise ValueError(msg)

            await self.adapter.delete_authorization_code_by_code_hash(session, code_hash=code_hash)
            if self._is_expired(code_record.expires_at):
                msg = "Authorization code expired"
                raise ValueError(msg)

            scope = " ".join(code_record.scopes)
            refresh_token = None
            if issue_refresh_token:
                refresh_token = await self._issue_refresh_token(
                    session,
                    client_id=code_record.client_id,
                    scopes=list(code_record.scopes),
                    individual_id=code_record.individual_id,
                    session_id=code_record.session_id,
                    resource=None,
                )

            access_token = await self._issue_access_token(
                session,
                client_id=code_record.client_id,
                scopes=list(code_record.scopes),
                resource=access_token_resource,
                refresh_token_id=refresh_token.id if refresh_token is not None else None,
                refresh_token=refresh_token.token if refresh_token is not None else None,
                individual_id=code_record.individual_id,
                session_id=code_record.session_id,
            )

        return OAuthServerToken(
            access_token=access_token.token,
            token_type="Bearer",  # noqa: S106
            expires_in=self._access_token_expires_in_seconds(code_record.scopes),
            expires_at=access_token.expires_at,
            scope=scope,
            refresh_token=refresh_token.token if refresh_token is not None else None,
        )

    async def persist_token_response(  # noqa: C901, PLR0913
        self,
        token: Mapping[str, object],
        *,
        client_id: str,
        scopes: list[str],
        resource: OAuthServerAudience | None = None,
        refresh_token_resource: str | None = None,
        individual_id: str | None = None,
        session_id: str | None = None,
        db: DBConnection | None = None,
    ) -> OAuthServerToken:
        access_token_value = token.get("access_token")
        if not isinstance(access_token_value, str) or not access_token_value:
            msg = "Token response missing access_token"
            raise ValueError(msg)

        parsed_individual_id = self._parse_uuid(individual_id)
        parsed_session_id = self._parse_uuid(session_id)

        issued_at = int(time.time())
        expires_in = token.get("expires_in")
        expires_at = self._expires_at(
            self._access_token_expires_in_seconds(
                scopes,
                is_machine_token=parsed_individual_id is None,
            )
            if not isinstance(expires_in, int)
            else expires_in,
        )

        signed_access_token = self.verify_signed_access_token(access_token_value, verify_exp=False)
        if signed_access_token is not None:
            issued_at = signed_access_token.created_at
            if signed_access_token.expires_at is not None:
                expires_at = datetime.fromtimestamp(signed_access_token.expires_at, UTC)
            if resource is None:
                resource = signed_access_token.resource
            if parsed_individual_id is None:
                parsed_individual_id = self._parse_uuid(signed_access_token.individual_id)
            if parsed_session_id is None:
                parsed_session_id = self._parse_uuid(signed_access_token.session_id)

        async with self._db_session(db, transactional=True) as session:
            persisted_refresh_token: RefreshToken | None = None
            refresh_token_value = token.get("refresh_token")
            if isinstance(refresh_token_value, str) and refresh_token_value:
                decoded_refresh_token = await self._decode_refresh_token(refresh_token_value)
                if decoded_refresh_token is None:
                    msg = "Invalid refresh token"
                    raise ValueError(msg)
                encoded_session_id, raw_refresh_token = decoded_refresh_token
                stored_session_id = parsed_session_id or self._parse_uuid(encoded_session_id)
                refresh_token_record = await self.adapter.create_refresh_token(
                    session,
                    token_hash=self._hash_value(raw_refresh_token),
                    client_id=client_id,
                    scopes=list(scopes),
                    resource=refresh_token_resource,
                    individual_id=parsed_individual_id,
                    session_id=stored_session_id,
                    expires_at=self._expires_at(self.settings.refresh_token_ttl_seconds),
                )
                persisted_refresh_token = self._refresh_token_from_record(
                    refresh_token_value,
                    refresh_token_record,
                )

            await self.adapter.create_access_token(
                session,
                token_hash=self._hash_value(self._strip_access_token_prefix(access_token_value)),
                client_id=client_id,
                scopes=list(scopes),
                resource=resource,
                refresh_token_id=(persisted_refresh_token.id if persisted_refresh_token is not None else None),
                individual_id=parsed_individual_id,
                session_id=parsed_session_id,
                expires_at=expires_at,
            )

        persisted_token = {
            "access_token": access_token_value,
            "token_type": token.get("token_type", "Bearer"),
            "expires_in": max(0, int(expires_at.timestamp()) - issued_at),
            "expires_at": int(expires_at.timestamp()),
            "scope": token.get("scope"),
        }
        if persisted_refresh_token is not None:
            persisted_token["refresh_token"] = persisted_refresh_token.token
        if "id_token" in token:
            persisted_token["id_token"] = token["id_token"]
        return OAuthServerToken.model_validate(persisted_token)

    async def load_access_token(
        self,
        token: str,
        *,
        db: DBConnection | None = None,
    ) -> AccessToken | None:
        normalized_token = self._normalize_supplied_access_token(token)
        if normalized_token is None:
            return None
        async with self._db_session(db, transactional=True) as session:
            access_token = await self.adapter.get_access_token_by_token_hash(
                session,
                token_hash=self._hash_value(normalized_token),
            )
            if access_token is None:
                return None
            if self._is_expired(access_token.expires_at):
                await self.adapter.delete_access_token_by_token_hash(session, token_hash=access_token.token_hash)
                return None
            return self._access_token_from_record(token, access_token)

    async def load_refresh_token(
        self,
        refresh_token_value: str,
        *,
        include_revoked: bool = False,
        db: DBConnection | None = None,
    ) -> RefreshToken | None:
        decoded_refresh_token = await self._decode_refresh_token(refresh_token_value)
        if decoded_refresh_token is None:
            return None
        _decoded_session_id, raw_refresh_token = decoded_refresh_token
        async with self._db_session(db, transactional=True) as session:
            refresh_token = await self.adapter.get_refresh_token_by_token_hash(
                session,
                token_hash=self._hash_value(raw_refresh_token),
            )
            if refresh_token is None:
                return None
            if self._is_expired(refresh_token.expires_at):
                await self.adapter.delete_refresh_token_by_token_hash(session, token_hash=refresh_token.token_hash)
                return None
            if refresh_token.revoked_at is not None and not include_revoked:
                return None
            return self._refresh_token_from_record(refresh_token_value, refresh_token)

    async def exchange_refresh_token(
        self,
        refresh_token: RefreshToken,
        scopes: list[str],
        *,
        access_token_resource: OAuthServerAudience | None = None,
        refresh_token_resource: str | None = None,
        db: DBConnection | None = None,
    ) -> OAuthServerToken:
        decoded_refresh_token = await self._decode_refresh_token(refresh_token.token)
        if decoded_refresh_token is None:
            msg = "Invalid refresh token"
            raise ValueError(msg)
        _decoded_session_id, raw_refresh_token = decoded_refresh_token
        token_hash = self._hash_value(raw_refresh_token)
        async with self._db_session(db, transactional=True) as session:
            stored_refresh_token = await self.adapter.get_refresh_token_by_token_hash(session, token_hash=token_hash)
            if stored_refresh_token is None:
                msg = "Invalid refresh token"
                raise ValueError(msg)

            if self._is_expired(stored_refresh_token.expires_at):
                await self.adapter.delete_refresh_token_by_token_hash(session, token_hash=token_hash)
                msg = "Refresh token expired"
                raise ValueError(msg)

            if stored_refresh_token.revoked_at is not None:
                await self._purge_refresh_token_family(session, stored_refresh_token)
                msg = "Refresh token has been revoked"
                raise ValueError(msg)

            invalid_scopes = [scope for scope in scopes if scope not in stored_refresh_token.scopes]
            if invalid_scopes:
                msg = f"Requested scope '{invalid_scopes[0]}' was not granted"
                raise ValueError(msg)

            revoked_refresh_token = await self.adapter.update_refresh_token_revoked_at(
                session,
                refresh_token_id=stored_refresh_token.id,
                revoked_at=datetime.fromtimestamp(time.time(), UTC),
            )
            if revoked_refresh_token is None:
                msg = "Invalid refresh token"
                raise ValueError(msg)

            new_refresh_token = await self._issue_refresh_token(
                session,
                client_id=stored_refresh_token.client_id,
                scopes=list(scopes),
                individual_id=stored_refresh_token.individual_id,
                session_id=stored_refresh_token.session_id,
                resource=refresh_token_resource,
            )
            access_token = await self._issue_access_token(
                session,
                client_id=stored_refresh_token.client_id,
                scopes=list(scopes),
                resource=access_token_resource,
                refresh_token_id=new_refresh_token.id,
                refresh_token=new_refresh_token.token,
                individual_id=stored_refresh_token.individual_id,
                session_id=stored_refresh_token.session_id,
            )

        return OAuthServerToken(
            access_token=access_token.token,
            token_type="Bearer",  # noqa: S106
            expires_in=self._access_token_expires_in_seconds(scopes),
            expires_at=access_token.expires_at,
            scope=" ".join(scopes),
            refresh_token=new_refresh_token.token,
        )

    async def issue_client_credentials_token(
        self,
        client_id: str,
        scopes: list[str],
        *,
        resource: OAuthServerAudience | None = None,
        db: DBConnection | None = None,
    ) -> OAuthServerToken:
        async with self._db_session(db, transactional=True) as session:
            access_token = await self._issue_access_token(
                session,
                client_id=client_id,
                scopes=scopes,
                resource=resource,
            )
        return OAuthServerToken(
            access_token=access_token.token,
            token_type="Bearer",  # noqa: S106
            expires_in=self._access_token_expires_in_seconds(scopes, is_machine_token=True),
            expires_at=access_token.expires_at,
            scope=" ".join(scopes),
        )

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
        *,
        db: DBConnection | None = None,
    ) -> None:
        async with self._db_session(db, transactional=True) as session:
            if isinstance(token, AccessToken):
                normalized_token = self._normalize_supplied_access_token(token.token)
                if normalized_token is None:
                    return
                await self.adapter.delete_access_token_by_token_hash(
                    session,
                    token_hash=self._hash_value(normalized_token),
                )
                return

            decoded_refresh_token = await self._decode_refresh_token(token.token)
            if decoded_refresh_token is None:
                return
            _decoded_session_id, raw_refresh_token = decoded_refresh_token
            stored_refresh_token = await self.adapter.get_refresh_token_by_token_hash(
                session,
                token_hash=self._hash_value(raw_refresh_token),
            )
            if stored_refresh_token is None:
                return

            await self.adapter.delete_access_tokens_by_refresh_token_id(
                session,
                refresh_token_id=stored_refresh_token.id,
            )
            await self.adapter.update_refresh_token_revoked_at(
                session,
                refresh_token_id=stored_refresh_token.id,
                revoked_at=datetime.fromtimestamp(time.time(), UTC),
            )

    async def revoke_refresh_token(
        self,
        refresh_token: RefreshToken,
        *,
        db: DBConnection | None = None,
    ) -> RefreshToken | None:
        decoded_refresh_token = await self._decode_refresh_token(refresh_token.token)
        if decoded_refresh_token is None:
            return None
        _decoded_session_id, raw_refresh_token = decoded_refresh_token
        async with self._db_session(db, transactional=True) as session:
            stored_refresh_token = await self.adapter.get_refresh_token_by_token_hash(
                session,
                token_hash=self._hash_value(raw_refresh_token),
            )
            if stored_refresh_token is None:
                return None
            revoked_refresh_token = await self.adapter.update_refresh_token_revoked_at(
                session,
                refresh_token_id=stored_refresh_token.id,
                revoked_at=datetime.fromtimestamp(time.time(), UTC),
            )
            if revoked_refresh_token is None:
                return None
            return self._refresh_token_from_record(refresh_token.token, revoked_refresh_token)

    async def purge_refresh_token_family(
        self,
        refresh_token: RefreshToken,
        *,
        db: DBConnection | None = None,
    ) -> None:
        decoded_refresh_token = await self._decode_refresh_token(refresh_token.token)
        if decoded_refresh_token is None:
            return
        _decoded_session_id, raw_refresh_token = decoded_refresh_token
        async with self._db_session(db, transactional=True) as session:
            stored_refresh_token = await self.adapter.get_refresh_token_by_token_hash(
                session,
                token_hash=self._hash_value(raw_refresh_token),
            )
            if stored_refresh_token is None:
                return
            await self._purge_refresh_token_family(session, stored_refresh_token)

    def default_scopes_for_client(
        self,
        client: OAuthServerClientInformationFull,
        *,
        grant_type: str | None = None,
    ) -> list[str]:
        if grant_type == "client_credentials" and self.settings.client_credentials_default_scopes is not None:
            return dedupe_scopes(self.settings.client_credentials_default_scopes)
        raw_scope = client.scope.strip() if client.scope else ""
        if raw_scope:
            return parse_scope_string(raw_scope) or []
        return list(self.settings.default_scopes)

    def validate_scopes_for_client(
        self,
        client: OAuthServerClientInformationFull,
        scopes: list[str],
        *,
        grant_type: str | None = None,
    ) -> None:
        if grant_type == "client_credentials":
            invalid_oidc_scopes = [
                scope for scope in scopes if scope in {"openid", "profile", "email", "offline_access"}
            ]
            if invalid_oidc_scopes:
                msg = f"scope {invalid_oidc_scopes[0]} is not allowed for client_credentials"
                raise ValueError(msg)
        allowed_scopes = set(self.default_scopes_for_client(client, grant_type=grant_type))
        invalid_scopes = [scope for scope in scopes if scope not in allowed_scopes]
        if invalid_scopes:
            msg = f"Client was not registered with scope {invalid_scopes[0]}"
            raise ValueError(msg)

    async def save_consent(
        self,
        client_id: str,
        individual_id: str,
        scopes: list[str],
        *,
        reference_id: str | None = None,
        db: DBConnection | None = None,
    ) -> None:
        merged_scopes = (
            list(existing.scopes)
            if (existing := await self.load_consent(client_id, individual_id, reference_id=reference_id, db=db))
            is not None
            else []
        )
        for scope in scopes:
            if scope not in merged_scopes:
                merged_scopes.append(scope)

        async with self._db_session(db, transactional=True) as session:
            await self.adapter.upsert_consent(
                session,
                client_id=client_id,
                individual_id=self._require_uuid(individual_id),
                reference_id=reference_id,
                scopes=dedupe_scopes(merged_scopes),
            )

    async def load_consent(
        self,
        client_id: str,
        individual_id: str,
        *,
        reference_id: str | None = None,
        db: DBConnection | None = None,
    ) -> ConsentEntry | None:
        async with self._db_session(db) as session:
            consent = await self.adapter.get_consent(
                session,
                client_id=client_id,
                individual_id=self._require_uuid(individual_id),
                reference_id=reference_id,
            )
            if consent is None:
                return None
            return self._consent_entry_from_record(consent)

    async def has_consent(
        self,
        client_id: str,
        individual_id: str,
        scopes: list[str],
        *,
        reference_id: str | None = None,
        db: DBConnection | None = None,
    ) -> bool:
        if (consent := await self.load_consent(client_id, individual_id, reference_id=reference_id, db=db)) is None:
            return False
        return all(scope in consent.scopes for scope in scopes)

    async def list_consents(
        self,
        individual_id: str,
        *,
        reference_id: str | None = None,
        db: DBConnection | None = None,
    ) -> list[ConsentEntry]:
        async with self._db_session(db) as session:
            consents = await self.adapter.list_consents(
                session,
                individual_id=self._require_uuid(individual_id),
                reference_id=reference_id,
            )
        return [self._consent_entry_from_record(consent) for consent in consents]

    async def get_consent_by_id(
        self,
        consent_id: UUID,
        *,
        db: DBConnection | None = None,
    ) -> ConsentEntry | None:
        async with self._db_session(db) as session:
            consent = await self.adapter.get_consent_by_id(session, consent_id=consent_id)
            if consent is None:
                return None
            return self._consent_entry_from_record(consent)

    async def update_consent(
        self,
        consent_id: UUID,
        *,
        scopes: list[str],
        db: DBConnection | None = None,
    ) -> ConsentEntry | None:
        async with self._db_session(db, transactional=True) as session:
            consent = await self.adapter.update_consent(session, consent_id=consent_id, scopes=dedupe_scopes(scopes))
            if consent is None:
                return None
            return self._consent_entry_from_record(consent)

    async def delete_consent(
        self,
        consent_id: UUID,
        *,
        db: DBConnection | None = None,
    ) -> bool:
        async with self._db_session(db, transactional=True) as session:
            return await self.adapter.delete_consent(session, consent_id=consent_id)

    def _allowed_dynamic_client_registration_scopes(self) -> list[str]:
        allowed_scopes = self.settings.client_registration_allowed_scopes or self.settings.supported_scopes()
        default_scopes = self.settings.client_registration_default_scopes or self.settings.default_scopes
        return dedupe_scopes([*default_scopes, *allowed_scopes])

    def resolve_subject_identifier(self, client: OAuthServerClientInformationFull, individual_id: str) -> str:
        if client.subject_type != "pairwise":
            return individual_id
        if self.settings.pairwise_secret is None:
            return individual_id
        if not client.redirect_uris:
            return individual_id
        sector_identifier = urlparse(str(client.redirect_uris[0])).netloc
        digest = hmac.new(
            self.settings.pairwise_secret.get_secret_value().encode("utf-8"),
            f"{sector_identifier}.{individual_id}".encode(),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")

    def validate_client_metadata(  # noqa: C901, PLR0912, PLR0915
        self,
        metadata: OAuthServerClientMetadata,
        *,
        allow_confidential_pkce_opt_out: bool = False,
        allow_privileged_fields: bool = False,
    ) -> None:
        token_endpoint_auth_method = metadata.token_endpoint_auth_method or "client_secret_basic"
        is_public = token_endpoint_auth_method == "none"  # noqa: S105
        grant_types = metadata.grant_types or ["authorization_code"]
        response_types = metadata.response_types or ["code"]
        allowed_grant_types = set(self.settings.grant_types)
        allowed_scopes = set(self._allowed_dynamic_client_registration_scopes())

        invalid_grant_types = [grant_type for grant_type in grant_types if grant_type not in allowed_grant_types]
        if invalid_grant_types:
            msg = f"unsupported grant_type {invalid_grant_types[0]}"
            raise ValueError(msg)
        invalid_response_types = [response_type for response_type in response_types if response_type != "code"]
        if invalid_response_types:
            msg = f"unsupported response_type {invalid_response_types[0]}"
            raise ValueError(msg)
        if "authorization_code" in grant_types and not metadata.redirect_uris:
            msg = "Redirect URIs are required for authorization_code clients"
            raise ValueError(msg)
        if "authorization_code" in grant_types and "code" not in response_types:
            msg = "When authorization_code is used, response_types must include code"
            raise ValueError(msg)
        if metadata.type is not None:
            if is_public and metadata.type not in {"native", "user-agent-based"}:
                msg = "Type must be native or user-agent-based for public clients"
                raise ValueError(msg)
            if not is_public and metadata.type != "web":
                msg = "Type must be web for confidential clients"
                raise ValueError(msg)
        if metadata.subject_type == "pairwise":
            if self.settings.pairwise_secret is None:
                msg = "pairwise subject_type requires pairwise_secret configuration"
                raise ValueError(msg)
            redirect_hosts = {urlparse(str(redirect_uri)).netloc for redirect_uri in metadata.redirect_uris or []}
            if len(redirect_hosts) > 1:
                msg = (
                    "pairwise clients with redirect_uris on different hosts require a "
                    "sector_identifier_uri, which is not yet supported. All redirect_uris "
                    "must share the same host."
                )
                raise ValueError(msg)
        if metadata.require_pkce is False and (is_public or not allow_confidential_pkce_opt_out):
            msg = "pkce is required for registered clients"
            raise ValueError(msg)
        extras = metadata.model_extra or {}
        if extras.get("jwks") is not None or extras.get("jwks_uri") is not None:
            msg = "jwks and jwks_uri client metadata fields are not yet supported"
            raise ValueError(msg)
        if metadata.skip_consent and not allow_privileged_fields:
            msg = "skip_consent cannot be set during dynamic client registration"
            raise ValueError(msg)
        if metadata.scope is not None:
            invalid_scopes = [
                scope for scope in (parse_scope_string(metadata.scope) or []) if scope and scope not in allowed_scopes
            ]
            if invalid_scopes:
                msg = f"cannot request scope {invalid_scopes[0]}"
                raise ValueError(msg)
        self._validate_with_authlib_claims(metadata)

    def _validate_with_authlib_claims(self, metadata: OAuthServerClientMetadata) -> None:
        payload = metadata.model_dump(mode="json", by_alias=True, exclude_none=True)
        server_metadata = self._authlib_server_metadata()

        for claims_class in (
            OAuth2ClientMetadataClaims,
            OIDCClientMetadataClaims,
            RPInitiatedClientMetadataClaims,
        ):
            options = (
                claims_class.get_claims_options(server_metadata)
                if hasattr(claims_class, "get_claims_options")
                else None
            )
            try:
                claims = claims_class(payload, {}, options, server_metadata)
                claims.validate()
            except (InvalidClaimError, ValueError) as exc:
                raise ValueError(str(exc)) from exc

    def _authlib_server_metadata(self) -> dict[str, object]:
        if "openid" in self.settings.supported_scopes():
            metadata = build_openid_metadata(self.issuer_url, self.settings).model_dump(
                mode="json",
                exclude_none=True,
            )
        else:
            metadata = build_oauth_metadata(self.issuer_url, self.settings).model_dump(
                mode="json",
                exclude_none=True,
            )

        auth_methods = list(metadata.get("token_endpoint_auth_methods_supported", []))
        if "none" not in auth_methods:
            auth_methods.insert(0, "none")
        metadata["token_endpoint_auth_methods_supported"] = auth_methods
        return metadata

    async def _issue_access_token(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        client_id: str,
        scopes: list[str],
        resource: OAuthServerAudience | None = None,
        refresh_token_id: UUID | None = None,
        refresh_token: str | None = None,
        individual_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> AccessToken:
        now = int(time.time())
        expires_in = self._access_token_expires_in_seconds(
            scopes,
            is_machine_token=individual_id is None,
        )
        expires_at = self._expires_at(expires_in)
        should_issue_signed_access_token = resource is not None and not self.settings.disable_jwt_plugin
        token_value = (
            await self._generate_signed_access_token(
                client_id=client_id,
                scopes=scopes,
                resource=resource,
                resource_value=resource if isinstance(resource, str) else None,
                individual_id=individual_id,
                session_id=session_id,
                issued_at=now,
                expires_at=int(expires_at.timestamp()),
            )
            if should_issue_signed_access_token
            else self._prefix_access_token(await self._generate_opaque_access_token())
        )
        access_token = await self.adapter.create_access_token(
            session,
            token_hash=self._hash_value(self._strip_access_token_prefix(token_value)),
            client_id=client_id,
            scopes=list(scopes),
            resource=resource,
            refresh_token_id=refresh_token_id,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=expires_at,
        )
        return AccessToken(
            token=token_value,
            client_id=access_token.client_id,
            scopes=list(access_token.scopes),
            created_at=now,
            expires_at=int(access_token.expires_at.timestamp()),
            resource=access_token.resource,
            refresh_token=refresh_token,
            individual_id=self._stringify_uuid(access_token.individual_id),
            session_id=self._stringify_uuid(access_token.session_id),
        )

    async def _issue_refresh_token(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        client_id: str,
        scopes: list[str],
        individual_id: UUID | None = None,
        session_id: UUID | None = None,
        resource: str | None = None,
    ) -> RefreshToken:
        token_body = await self._generate_refresh_token()
        refresh_token = await self.adapter.create_refresh_token(
            session,
            token_hash=self._hash_value(token_body),
            client_id=client_id,
            scopes=list(scopes),
            resource=resource,
            individual_id=individual_id,
            session_id=session_id,
            expires_at=self._expires_at(self.settings.refresh_token_ttl_seconds),
        )
        return self._refresh_token_from_record(await self._encode_refresh_token(token_body, session_id), refresh_token)

    def verify_signed_access_token(
        self,
        token: str,
        *,
        audience: str | list[str] | None = None,
        verify_exp: bool = True,
    ) -> AccessToken | None:
        try:
            payload = self.signing_state.decode(
                token,
                audience=audience,
                issuer=self.issuer_url,
                verify_exp=verify_exp,
            )
        except JoseError:
            return None

        client_id = payload.get("azp")
        if not isinstance(client_id, str) or not client_id:
            return None

        scopes = parse_scope_string(payload.get("scope")) or []
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        subject = payload.get("sub")
        session_id = payload.get("sid")
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            created_at=issued_at if isinstance(issued_at, int) else int(time.time()),
            expires_at=expires_at if isinstance(expires_at, int) else None,
            resource=payload.get("aud") if isinstance(payload.get("aud"), (str, list)) else None,
            individual_id=subject if isinstance(subject, str) else None,
            session_id=session_id if isinstance(session_id, str) else None,
            claims=dict(payload),
        )

    async def _purge_refresh_token_family(
        self,
        session: DBConnection,
        refresh_token: OAuthServerRefreshTokenProtocol,
    ) -> None:
        if refresh_token.individual_id is not None:
            await self.adapter.delete_access_tokens_for_client_and_individual(
                session,
                client_id=refresh_token.client_id,
                individual_id=refresh_token.individual_id,
            )
            await self.adapter.delete_refresh_tokens_for_client_and_individual(
                session,
                client_id=refresh_token.client_id,
                individual_id=refresh_token.individual_id,
            )
            return

        await self.adapter.delete_access_tokens_by_refresh_token_id(session, refresh_token_id=refresh_token.id)
        await self.adapter.delete_refresh_token_by_token_hash(session, token_hash=refresh_token.token_hash)

    @asynccontextmanager
    async def _managed_session(
        self,
        session: DBConnection,
        *,
        transactional: bool,
        close: bool,
    ) -> AsyncGenerator[DBConnection, None]:
        try:
            yield session
            if transactional:
                await session.commit()
        except Exception:
            if transactional:
                await session.rollback()
            raise
        finally:
            if close:
                await session.close()

    @asynccontextmanager
    async def _db_session(
        self,
        db: DBConnection | None,
        *,
        transactional: bool = False,
    ) -> AsyncGenerator[DBConnection, None]:
        if db is not None:
            async with self._managed_session(db, transactional=transactional, close=False) as session:
                yield session
            return

        if self.database_factory is None:
            msg = "A database session is required to use the OAuth server adapter"
            raise RuntimeError(msg)

        db_or_generator = self.database_factory()
        if isinstance(db_or_generator, DBConnection):
            async with self._managed_session(db_or_generator, transactional=transactional, close=True) as session:
                yield session
            return

        if self._is_async_generator(db_or_generator):
            async with aclosing(db_or_generator) as db_generator:
                async for session in db_generator:
                    async with self._managed_session(
                        session,
                        transactional=transactional,
                        close=False,
                    ) as managed_session:
                        yield managed_session
                    return

        msg = "database() must return a DBConnection or AsyncGenerator[DBConnection, None]"
        raise TypeError(msg)

    @staticmethod
    def _is_async_generator(value: object) -> bool:
        return isinstance(value, AsyncGenerator)

    async def _generate_client_id(self) -> str:
        if self.settings.generate_client_id is not None:
            generated = self.settings.generate_client_id()
            if isinstance(generated, str):
                return generated
            return await generated
        return f"belgie_client_{secrets.token_hex(8)}"

    async def _generate_client_secret(self) -> str:
        if self.settings.generate_client_secret is not None:
            generated = self.settings.generate_client_secret()
            if isinstance(generated, str):
                return generated
            return await generated
        return secrets.token_hex(16)

    def _store_client_secret(self, client_secret: str) -> tuple[str | None, str]:
        if self.settings.signing.algorithm == "HS256":
            return client_secret, self._hash_value(client_secret)
        return None, self._hash_value(client_secret)

    def _resolve_client_secret_expiration(
        self,
        configured: int | str | datetime | None | object = _UNSET,
    ) -> int | None:
        if configured is _UNSET:
            configured = self.settings.client_registration_client_secret_expires_at
        if configured is None:
            return None
        if isinstance(configured, datetime):
            return int(configured.timestamp())
        if isinstance(configured, str):
            stripped = configured.strip().lower()
            if stripped.lstrip("-").isdigit():
                return int(stripped)
            return _resolve_time_span_to_timestamp(stripped)
        return configured

    def _prefix_client_secret(self, client_secret: str) -> str:
        if self.settings.token_prefixes.client_secret:
            return f"{self.settings.token_prefixes.client_secret}{client_secret}"
        return client_secret

    def _strip_client_secret_prefix(self, client_secret: str | None) -> str | None:
        if client_secret is None:
            return None
        prefix = self.settings.token_prefixes.client_secret
        if prefix and client_secret.startswith(prefix):
            return client_secret.removeprefix(prefix)
        return client_secret

    def _normalize_supplied_client_secret(self, client_secret: str | None) -> str | None:
        if client_secret is None:
            return None
        prefix = self.settings.token_prefixes.client_secret
        if prefix is None:
            return client_secret
        if not client_secret.startswith(prefix):
            return None
        return client_secret.removeprefix(prefix)

    async def _generate_opaque_access_token(self) -> str:
        if self.settings.generate_access_token is not None:
            generated = self.settings.generate_access_token()
            if isinstance(generated, str):
                return generated
            return await generated
        return f"belgie_{secrets.token_hex(16)}"

    async def _generate_refresh_token(self) -> str:
        if self.settings.generate_refresh_token is not None:
            generated = self.settings.generate_refresh_token()
            if isinstance(generated, str):
                return generated
            return await generated
        return f"belgie_refresh_{secrets.token_hex(16)}"

    async def _generate_signed_access_token(  # noqa: PLR0913
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: OAuthServerAudience,
        resource_value: str | None = None,
        individual_id: UUID | None,
        session_id: UUID | None,
        issued_at: int,
        expires_at: int,
        oauth_client: OAuthServerClientInformationFull | None = None,
        user: object | None = None,
        reference_id: str | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "iss": self.issuer_url,
            "sub": self._stringify_uuid(individual_id),
            "aud": resource if not isinstance(resource, list) or len(resource) != 1 else resource[0],
            "azp": client_id,
            "scope": " ".join(scopes),
            "iat": issued_at,
            "exp": expires_at,
        }
        if session_id is not None:
            payload["sid"] = str(session_id)

        custom_claims = await self._resolve_custom_claims(
            self.settings.custom_access_token_claims,
            {
                "user": user,
                "reference_id": reference_id,
                "client_id": client_id,
                "scopes": list(scopes),
                "resource": resource_value if resource_value is not None else resource,
                "individual_id": self._stringify_uuid(individual_id),
                "session_id": self._stringify_uuid(session_id),
                "metadata": {} if oauth_client is None else (oauth_client.metadata_json or {}),
                "metadata_json": {} if oauth_client is None else (oauth_client.metadata_json or {}),
            },
        )
        payload.update(
            {key: value for key, value in custom_claims.items() if key not in _RESERVED_ACCESS_TOKEN_CLAIMS},
        )
        return self.signing_state.sign(payload)

    async def _encode_refresh_token(self, token: str, session_id: UUID | None) -> str:
        encoded = token
        if self.settings.refresh_token_encoder is not None:
            resolved = self.settings.refresh_token_encoder(encoded, self._stringify_uuid(session_id))
            encoded = await resolved if isawaitable(resolved) else resolved
        if self.settings.token_prefixes.refresh_token:
            return f"{self.settings.token_prefixes.refresh_token}{encoded}"
        return encoded

    async def _decode_refresh_token(self, token: str) -> tuple[str | None, str] | None:
        decoded = token
        prefix = self.settings.token_prefixes.refresh_token
        if prefix and decoded.startswith(prefix):
            decoded = decoded.removeprefix(prefix)
        elif prefix:
            return None

        if self.settings.refresh_token_decoder is None:
            return None, decoded

        resolved = self.settings.refresh_token_decoder(decoded)
        return await resolved if isawaitable(resolved) else resolved

    def _prefix_access_token(self, token: str) -> str:
        if self.settings.token_prefixes.access_token:
            return f"{self.settings.token_prefixes.access_token}{token}"
        return token

    def _strip_access_token_prefix(self, token: str) -> str:
        prefix = self.settings.token_prefixes.access_token
        if prefix and token.startswith(prefix):
            return token.removeprefix(prefix)
        return token

    def _normalize_supplied_access_token(self, token: str) -> str | None:
        prefix = self.settings.token_prefixes.access_token
        if prefix is None:
            return token
        if token.startswith(prefix):
            return token.removeprefix(prefix)
        if token.count(".") == JWT_DELIMITER_COUNT:
            return token
        return None

    def _access_token_expires_in_seconds(
        self,
        scopes: list[str],
        *,
        is_machine_token: bool = False,
    ) -> int:
        default_exp = (
            self.settings.m2m_access_token_ttl_seconds if is_machine_token else self.settings.access_token_ttl_seconds
        )
        if not self.settings.scope_expirations:
            return default_exp

        expirations = [
            self.settings.scope_expirations[scope] for scope in scopes if scope in self.settings.scope_expirations
        ]
        if not expirations:
            return default_exp
        return min([default_exp, *expirations])

    async def _resolve_custom_claims(
        self,
        resolver: Callable[[dict[str, object]], dict[str, object] | Awaitable[dict[str, object]]] | None,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if resolver is None:
            return {}
        resolved = resolver(payload)
        claims = await resolved if isawaitable(resolved) else resolved
        return dict(claims)

    @staticmethod
    def _hash_value(value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def _stringify_uuid(value: UUID | None) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _parse_uuid(value: str | None) -> UUID | None:
        return None if value is None else UUID(value)

    @classmethod
    def _require_uuid(cls, value: str) -> UUID:
        return UUID(value)

    @staticmethod
    def _expires_at(ttl_seconds: int) -> datetime:
        return datetime.fromtimestamp(time.time() + max(ttl_seconds, 0), UTC)

    @classmethod
    def _state_expires_at(cls, ttl_seconds: int) -> datetime:
        if ttl_seconds <= 0:
            return cls._NON_EXPIRING_STATE_EXPIRES_AT
        return cls._expires_at(ttl_seconds)

    @staticmethod
    def _is_expired(expires_at: datetime) -> bool:
        return expires_at.timestamp() <= time.time()

    async def _delete_expired_state_if_needed(
        self,
        session: DBConnection,
        state_record: OAuthServerAuthorizationStateProtocol,
    ) -> bool:
        if not self._is_expired(state_record.expires_at):
            return False
        await self.adapter.delete_authorization_state(session, state=state_record.state)
        return True

    async def _delete_expired_authorization_code_if_needed(
        self,
        session: DBConnection,
        code_record: OAuthServerAuthorizationCodeProtocol,
    ) -> bool:
        if not self._is_expired(code_record.expires_at):
            return False
        await self.adapter.delete_authorization_code_by_code_hash(session, code_hash=code_record.code_hash)
        return True

    def _client_information_from_record(
        self,
        client: OAuthServerClientProtocol,
    ) -> OAuthServerClientInformationFull:
        return OAuthServerClientInformationFull(
            client_id=client.client_id,
            client_secret=client.client_secret,
            disabled=client.disabled,
            skip_consent=client.skip_consent,
            redirect_uris=[AnyUrl(uri) for uri in client.redirect_uris] if client.redirect_uris is not None else None,
            post_logout_redirect_uris=(
                [AnyUrl(uri) for uri in client.post_logout_redirect_uris]
                if client.post_logout_redirect_uris is not None
                else None
            ),
            token_endpoint_auth_method=client.token_endpoint_auth_method,
            grant_types=list(client.grant_types),
            response_types=list(client.response_types),
            scope=client.scope,
            client_name=client.client_name,
            client_uri=AnyUrl(client.client_uri) if client.client_uri is not None else None,
            logo_uri=AnyUrl(client.logo_uri) if client.logo_uri is not None else None,
            contacts=list(client.contacts) if client.contacts is not None else None,
            tos_uri=AnyUrl(client.tos_uri) if client.tos_uri is not None else None,
            policy_uri=AnyUrl(client.policy_uri) if client.policy_uri is not None else None,
            software_id=client.software_id,
            software_version=client.software_version,
            software_statement=client.software_statement,
            type=client.type,
            subject_type=client.subject_type,
            require_pkce=client.require_pkce,
            client_id_issued_at=client.client_id_issued_at,
            client_secret_expires_at=client.client_secret_expires_at,
            enable_end_session=client.enable_end_session,
            individual_id=self._stringify_uuid(client.individual_id),
            reference_id=client.reference_id,
            metadata_json=client.metadata_json,
        )

    @staticmethod
    def _state_entry_from_record(state_record: OAuthServerAuthorizationStateProtocol) -> StateEntry:
        return StateEntry(
            state=state_record.state,
            client_state=getattr(state_record, "client_state", state_record.state),
            redirect_uri=state_record.redirect_uri,
            code_challenge=state_record.code_challenge,
            redirect_uri_provided_explicitly=state_record.redirect_uri_provided_explicitly,
            client_id=state_record.client_id,
            resource=state_record.resource,
            scopes=list(state_record.scopes) if state_record.scopes is not None else None,
            created_at=state_record.created_at.timestamp(),
            nonce=state_record.nonce,
            prompt=state_record.prompt,
            intent=state_record.intent,
            individual_id=SimpleOAuthProvider._stringify_uuid(state_record.individual_id),
            session_id=SimpleOAuthProvider._stringify_uuid(state_record.session_id),
        )

    @staticmethod
    def _authorization_code_from_record(
        authorization_code: str,
        code_record: OAuthServerAuthorizationCodeProtocol,
    ) -> AuthorizationCode:
        return AuthorizationCode(
            code=authorization_code,
            scopes=list(code_record.scopes),
            expires_at=code_record.expires_at.timestamp(),
            client_id=code_record.client_id,
            code_challenge=code_record.code_challenge,
            redirect_uri=AnyUrl(code_record.redirect_uri),
            redirect_uri_provided_explicitly=code_record.redirect_uri_provided_explicitly,
            resource=code_record.resource,
            nonce=code_record.nonce,
            individual_id=SimpleOAuthProvider._stringify_uuid(code_record.individual_id),
            session_id=SimpleOAuthProvider._stringify_uuid(code_record.session_id),
        )

    @staticmethod
    def _access_token_from_record(
        token: str,
        access_token: OAuthServerAccessTokenProtocol,
    ) -> AccessToken:
        return AccessToken(
            token=token,
            client_id=access_token.client_id,
            scopes=list(access_token.scopes),
            created_at=int(access_token.created_at.timestamp()),
            expires_at=int(access_token.expires_at.timestamp()),
            resource=access_token.resource,
            individual_id=SimpleOAuthProvider._stringify_uuid(access_token.individual_id),
            session_id=SimpleOAuthProvider._stringify_uuid(access_token.session_id),
        )

    @staticmethod
    def _refresh_token_from_record(
        token: str,
        refresh_token: OAuthServerRefreshTokenProtocol,
    ) -> RefreshToken:
        return RefreshToken(
            id=refresh_token.id,
            token=token,
            client_id=refresh_token.client_id,
            scopes=list(refresh_token.scopes),
            created_at=int(refresh_token.created_at.timestamp()),
            expires_at=int(refresh_token.expires_at.timestamp()),
            revoked_at=(None if refresh_token.revoked_at is None else int(refresh_token.revoked_at.timestamp())),
            resource=refresh_token.resource,
            individual_id=SimpleOAuthProvider._stringify_uuid(refresh_token.individual_id),
            session_id=SimpleOAuthProvider._stringify_uuid(refresh_token.session_id),
        )

    @staticmethod
    def _consent_entry_from_record(consent: OAuthServerConsentProtocol) -> ConsentEntry:
        return ConsentEntry(
            id=consent.id,
            client_id=consent.client_id,
            individual_id=str(consent.individual_id),
            reference_id=consent.reference_id,
            scopes=list(consent.scopes),
            created_at=int(consent.created_at.timestamp()),
        )
