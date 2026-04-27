"""OAuth 2.1 / OIDC server routes and FastAPI integration.

Registers authorize, token, register, introspect, revoke, userinfo, end-session, consent, login, continue, and client
RPCs; RFC 9207 ``iss`` on success redirects, PKCE, per-endpoint rate limits, and DCR without ``jwks``/``jwks_uri`` in
registration metadata.
"""

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, Literal, Protocol
from urllib.parse import parse_qsl, urlparse, urlunparse
from uuid import UUID

from belgie_core.core.belgie import Belgie
from belgie_core.core.client import BelgieClient
from belgie_core.core.plugin import PluginClient
from belgie_core.core.settings import BelgieSettings
from belgie_proto.core.json import JSONValue
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import SecurityScopes
from joserfc import jws
from joserfc.errors import JoseError
from joserfc.util import to_bytes
from pydantic import AnyUrl, ValidationError
from starlette.datastructures import FormData

from belgie_oauth_server.client import OAuthLoginFlowClient, OAuthServerLoginIntent
from belgie_oauth_server.engine import BelgieOAuthServerEngine
from belgie_oauth_server.engine.helpers import (
    oauth_client_is_public,
    parse_scope_param,
    validate_pkce_inputs,
)
from belgie_oauth_server.engine.token_response import build_access_token_jwt_payload, build_user_claims
from belgie_oauth_server.metadata import (
    build_oauth_metadata,
    build_oauth_metadata_well_known_path,
    build_openid_metadata,
    build_openid_metadata_well_known_path,
)
from belgie_oauth_server.models import (
    InvalidRedirectUriError,
    OAuthServerAdminClientMetadata,
    OAuthServerClientInformationFull,
    OAuthServerClientMetadata,
    OAuthServerClientRpcResponse,
    OAuthServerConsentRpcResponse,
    OAuthServerErrorResponse,
    OAuthServerIntrospectionResponse,
    OAuthServerJwksResponse,
    OAuthServerMetadata,
    OAuthServerToken,
    OIDCMetadata,
    UserInfoResponse,
)
from belgie_oauth_server.provider import AuthorizationParams, SimpleOAuthProvider, StateEntry
from belgie_oauth_server.query_signature import (
    build_signed_oauth_query,
    parse_verified_oauth_query,
    verify_oauth_query_params,
)
from belgie_oauth_server.rate_limit import OAuthServerRateLimiter
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import (
    construct_redirect_uri,
    is_fetch_request,
    join_url,
    redirect_uris_match,
)
from belgie_oauth_server.verifier import verify_local_access_token

_OAUTH_ENDPOINT_PREFIX = "/oauth2"
type FormValue = str | UploadFile
type FormInput = Mapping[str, FormValue] | FormData
type AuthorizePrompt = Literal["none", "consent", "login", "create", "select_account"]

_PUBLIC_CLIENT_CREATE_FIELDS = frozenset(
    {
        "redirect_uris",
        "scope",
        "client_name",
        "client_uri",
        "logo_uri",
        "contacts",
        "tos_uri",
        "policy_uri",
        "software_id",
        "software_version",
        "software_statement",
        "post_logout_redirect_uris",
        "token_endpoint_auth_method",
        "grant_types",
        "response_types",
        "type",
    },
)
_PUBLIC_CLIENT_UPDATE_FIELDS = frozenset(
    {
        "redirect_uris",
        "scope",
        "client_name",
        "client_uri",
        "logo_uri",
        "contacts",
        "tos_uri",
        "policy_uri",
        "software_id",
        "software_version",
        "software_statement",
        "post_logout_redirect_uris",
        "grant_types",
        "response_types",
        "type",
    },
)
_ADMIN_CLIENT_CREATE_FIELDS = frozenset(
    {
        *_PUBLIC_CLIENT_CREATE_FIELDS,
        "client_secret_expires_at",
        "skip_consent",
        "enable_end_session",
        "require_pkce",
        "subject_type",
        "metadata",
    },
)
_ADMIN_CLIENT_UPDATE_FIELDS = frozenset(
    {
        *_PUBLIC_CLIENT_UPDATE_FIELDS,
        "client_secret_expires_at",
        "skip_consent",
        "enable_end_session",
        "metadata",
    },
)
_REGISTER_CLIENT_FIELDS = frozenset(
    {
        "redirect_uris",
        "scope",
        "client_name",
        "client_uri",
        "logo_uri",
        "contacts",
        "tos_uri",
        "policy_uri",
        "software_id",
        "software_version",
        "software_statement",
        "post_logout_redirect_uris",
        "token_endpoint_auth_method",
        "grant_types",
        "response_types",
        "type",
        "subject_type",
    },
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _AuthorizeRequestContext:
    oauth_client: OAuthServerClientInformationFull
    params: AuthorizationParams
    prompt_values: frozenset[AuthorizePrompt]
    redirect_uri: str
    raw_params: dict[str, str]


def _resolve_oauth_query_secret(belgie: Belgie, settings: OAuthServer) -> str:
    if settings.oauth_query_signing_secret is not None:
        return settings.oauth_query_signing_secret.get_secret_value()
    return belgie.settings.secret


def _authorization_query_parts(
    oauth_client: OAuthServerClientInformationFull,
    raw_params: dict[str, str],
    params: AuthorizationParams,
    state_key: str,
) -> dict[str, str | list[str] | None]:
    parts: dict[str, str | list[str] | None] = {
        "response_type": "code",
        "client_id": oauth_client.client_id,
        "redirect_uri": str(params.redirect_uri),
        "state": state_key,
    }
    if params.scopes:
        parts["scope"] = " ".join(params.scopes)
    if params.code_challenge:
        parts["code_challenge"] = params.code_challenge
        parts["code_challenge_method"] = params.code_challenge_method or "S256"
    if params.nonce:
        parts["nonce"] = params.nonce
    if params.prompt:
        parts["prompt"] = params.prompt
    for key in (
        "request_uri",
        "display",
        "ui_locales",
        "max_age",
        "acr_values",
        "login_hint",
        "id_token_hint",
    ):
        if raw_params.get(key):
            parts[key] = raw_params[key]
    return parts


def _authorization_query_parts_for_state(
    state_key: str,
    data: StateEntry,
) -> dict[str, str | list[str] | None]:
    parts: dict[str, str | list[str] | None] = {
        "response_type": "code",
        "client_id": data.client_id,
        "redirect_uri": data.redirect_uri,
        "state": state_key,
    }
    if data.scopes:
        parts["scope"] = " ".join(data.scopes)
    if data.code_challenge:
        parts["code_challenge"] = data.code_challenge
        parts["code_challenge_method"] = "S256"
    if data.nonce:
        parts["nonce"] = data.nonce
    if data.prompt:
        parts["prompt"] = data.prompt
    return parts


def _signed_oauth_query_string(  # noqa: PLR0913
    oauth_client: OAuthServerClientInformationFull,
    raw_params: dict[str, str],
    params: AuthorizationParams,
    *,
    state_key: str,
    secret: str,
    settings: OAuthServer,
) -> str:
    parts = _authorization_query_parts(oauth_client, raw_params, params, state_key)
    return build_signed_oauth_query(
        parts,
        secret=secret,
        code_expires_in_seconds=settings.authorization_code_ttl_seconds,
    )


def _wants_interaction_json(request: Request) -> bool:
    if request.method == "GET":
        return False
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return True
    content_type = request.headers.get("content-type", "")
    return content_type.startswith("application/json")


def _interaction_response(request: Request, redirect_url: str) -> Response:
    if _wants_interaction_json(request):
        return JSONResponse({"redirect": True, "url": redirect_url, "redirect_uri": redirect_url})
    return _redirect_response(request, redirect_url)


def _state_from_interaction_payload(
    payload: Mapping[str, JSONValue],
    belgie: Belgie,
    settings: OAuthServer,
) -> str:
    oauth_q = _get_payload_str(payload, "oauth_query")
    if oauth_q is not None and oauth_q != "":
        secret = _resolve_oauth_query_secret(belgie, settings)
        if not verify_oauth_query_params(oauth_q, secret):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_signature",
            )
        parsed = parse_verified_oauth_query(oauth_q, secret)
        st = (parsed or {}).get("state")
        if not isinstance(st, str) or not st:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state in oauth_query")
        return st
    st = _get_payload_str(payload, "state")
    if isinstance(st, str) and st:
        return st
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state")


def _get_payload_post_login_flag(payload: Mapping[str, JSONValue]) -> bool | None:
    for key in ("postLogin", "post_login"):
        v = _get_payload_bool(payload, key)
        if v is not None:
            return v
    return None


def _url_with_merged_query(base: str, query_string: str) -> str:
    return f"{base}&{query_string}" if "?" in base else f"{base}?{query_string}"


def _interaction_redirect_for_signed_query(
    *,
    issuer_url: str,
    belgie_base_url: str,
    settings: OAuthServer,
    intent: OAuthServerLoginIntent,
    signed_query: str,
) -> str:
    target = _resolve_auth_redirect_url(
        settings,
        belgie_base_url,
        intent=intent,
    )
    if target is None:
        return _url_with_merged_query(join_url(issuer_url, "oauth2/login"), signed_query)
    return _url_with_merged_query(target, signed_query)


def _build_login_with_signed_query(  # noqa: PLR0913
    *,
    issuer_url: str,
    belgie_base_url: str,
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    raw_params: dict[str, str],
    params: AuthorizationParams,
    state_key: str,
    secret: str,
) -> str:
    signed = _signed_oauth_query_string(
        oauth_client,
        raw_params,
        params,
        state_key=state_key,
        secret=secret,
        settings=settings,
    )
    return _interaction_redirect_for_signed_query(
        issuer_url=issuer_url,
        belgie_base_url=belgie_base_url,
        settings=settings,
        intent=params.intent,
        signed_query=signed,
    )


def _build_resume_login_with_signed_query(  # noqa: PLR0913
    *,
    issuer_url: str,
    belgie_base_url: str,
    settings: OAuthServer,
    state_key: str,
    state_data: StateEntry,
    secret: str,
    intent: OAuthServerLoginIntent,
) -> str:
    parts = _authorization_query_parts_for_state(state_key, state_data)
    signed = build_signed_oauth_query(
        parts,
        secret=secret,
        code_expires_in_seconds=settings.authorization_code_ttl_seconds,
    )
    return _interaction_redirect_for_signed_query(
        issuer_url=issuer_url,
        belgie_base_url=belgie_base_url,
        settings=settings,
        intent=intent,
        signed_query=signed,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class _InteractionError:
    error: str
    description: str


class _ConsentLike(Protocol):
    id: UUID
    client_id: str
    individual_id: str
    reference_id: str | None
    scopes: list[str]
    created_at: datetime


class OAuthServerPlugin(PluginClient):
    def __init__(self, _belgie_settings: BelgieSettings, settings: OAuthServer) -> None:
        self._settings = settings
        self._provider: SimpleOAuthProvider | None = None
        self._engine: BelgieOAuthServerEngine | None = None
        self._metadata_router: APIRouter | None = None
        self._resolve_client: Callable[..., OAuthLoginFlowClient] | None = None
        self._rate_limiter = OAuthServerRateLimiter()

    @property
    def settings(self) -> OAuthServer:
        return self._settings

    @property
    def provider(self) -> SimpleOAuthProvider | None:
        return self._provider

    def _ensure_dependency_resolver(self, belgie: Belgie, provider: SimpleOAuthProvider, issuer_url: str) -> None:
        if self._resolve_client is not None:
            return

        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        def resolve_client(_client: BelgieClientDep) -> OAuthLoginFlowClient:
            return OAuthLoginFlowClient(provider=provider, issuer_url=issuer_url)

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    def __call__(self, *args: object, **kwargs: object) -> OAuthLoginFlowClient:
        if self._resolve_client is None:
            msg = (
                "OAuthServerPlugin dependency requires router initialization "
                "(call app.include_router(belgie.router) first)"
            )
            raise RuntimeError(msg)
        return self._resolve_client(*args, **kwargs)

    def router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )
        if self._provider is None:
            self._provider = SimpleOAuthProvider(
                self._settings,
                issuer_url=issuer_url,
                database_factory=belgie.database,
                fallback_signing_secret=belgie.settings.secret,
            )
        provider = self._provider
        self._engine = BelgieOAuthServerEngine(
            provider=provider,
            settings=self._settings,
            belgie_base_url=belgie.settings.base_url,
            issuer_url=issuer_url,
        )
        self._ensure_dependency_resolver(belgie, provider, issuer_url)

        self._metadata_router = self.metadata_router(belgie)

        router = APIRouter(tags=["oauth"])
        metadata = build_oauth_metadata(issuer_url, self._settings)
        openid_metadata = build_openid_metadata(issuer_url, self._settings)

        router = self._add_metadata_route(router, metadata)
        router = self._add_openid_metadata_route(router, openid_metadata)
        router = self._add_jwks_route(router, provider, self._settings)
        if self._settings.supports_authorization_code():
            router = self._add_authorize_route(
                router,
                belgie,
                provider,
                self._settings,
                issuer_url,
                self._rate_limiter,
            )
        router = self._add_token_route(
            router,
            belgie,
            self._engine,
            self._settings,
            self._rate_limiter,
        )
        router = self._add_register_route(router, belgie, provider, self._settings, self._rate_limiter)
        router = self._add_revoke_route(router, belgie, self._engine, self._settings, self._rate_limiter)
        router = self._add_userinfo_route(router, belgie, provider, self._settings, issuer_url, self._rate_limiter)
        router = self._add_end_session_route(router, belgie, provider, issuer_url)
        if self._settings.supports_authorization_code():
            router = self._add_login_route(router, belgie, issuer_url, self._settings, provider)
            router = self._add_continue_route(router, belgie, provider, self._settings, issuer_url)
            router = self._add_consent_route(router, belgie, provider, self._settings, issuer_url)
            router = self._add_login_callback_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_client_management_routes(router, belgie, provider, self._settings)
        router = self._add_consent_management_routes(router, belgie, provider, self._settings)
        return self._add_introspect_route(router, belgie, self._engine, self._settings, self._rate_limiter)

    def metadata_router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )
        metadata = build_oauth_metadata(issuer_url, self._settings)
        openid_metadata = build_openid_metadata(issuer_url, self._settings)
        well_known_path = build_oauth_metadata_well_known_path(issuer_url)
        openid_well_known_path = build_openid_metadata_well_known_path(issuer_url)

        router = APIRouter(tags=["oauth"])

        async def metadata_handler(_: Request) -> OAuthServerMetadata:
            return metadata

        async def openid_metadata_handler(_: Request) -> OIDCMetadata:
            return openid_metadata

        router.add_api_route(
            well_known_path,
            metadata_handler,
            methods=["GET"],
            response_model=OAuthServerMetadata,
            response_model_exclude_none=True,
        )

        router.add_api_route(
            openid_well_known_path,
            openid_metadata_handler,
            methods=["GET"],
            response_model=OIDCMetadata,
            response_model_exclude_none=True,
        )

        return router

    def public(self, belgie: Belgie) -> APIRouter:
        if self._metadata_router is None:
            self._metadata_router = self.metadata_router(belgie)
        return self._metadata_router

    @staticmethod
    def _add_metadata_route(router: APIRouter, metadata: OAuthServerMetadata) -> APIRouter:
        async def metadata_handler(_: Request) -> OAuthServerMetadata:
            return metadata

        router.add_api_route(
            "/.well-known/oauth-authorization-server",
            metadata_handler,
            methods=["GET"],
            response_model=OAuthServerMetadata,
            response_model_exclude_none=True,
        )
        return router

    @staticmethod
    def _add_openid_metadata_route(router: APIRouter, metadata: OIDCMetadata) -> APIRouter:
        async def metadata_handler(_: Request) -> OIDCMetadata:
            return metadata

        router.add_api_route(
            "/.well-known/openid-configuration",
            metadata_handler,
            methods=["GET"],
            response_model=OIDCMetadata,
            response_model_exclude_none=True,
        )
        return router

    @staticmethod
    def _add_jwks_route(router: APIRouter, provider: SimpleOAuthProvider, settings: OAuthServer) -> APIRouter:
        async def jwks_handler(_: Request) -> OAuthServerJwksResponse:
            if settings.disable_jwt_plugin or provider.signing_state.jwks is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="jwks unavailable")
            jwks = provider.signing_state.jwks
            return OAuthServerJwksResponse.model_validate(jwks)

        router.add_api_route(
            "/jwks",
            jwks_handler,
            methods=["GET"],
            response_model=OAuthServerJwksResponse,
        )
        return router

    @staticmethod
    def _add_authorize_route(  # noqa: C901, PLR0913
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        issuer_url: str,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        async def _authorize(  # noqa: PLR0911
            request: Request,
            client: BelgieClient,
        ) -> Response:
            if (
                rate_limited := _enforce_rate_limit(
                    request,
                    rate_limiter,
                    "authorize",
                    settings.rate_limit.authorize,
                )
            ) is not None:
                return rate_limited
            data = await _get_request_params(request)
            authorize_request = await _parse_authorize_request(
                data,
                provider,
                settings,
                belgie.settings.base_url,
                issuer_url,
            )
            if isinstance(authorize_request, Response):
                return authorize_request

            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    if "none" in authorize_request.prompt_values:
                        return _authorize_error(
                            "login_required",
                            "authentication required",
                            redirect_uri=authorize_request.redirect_uri,
                            state=authorize_request.params.state,
                            issuer_url=issuer_url,
                        )
                    if (
                        _resolve_auth_redirect_url(
                            settings,
                            belgie.settings.base_url,
                            intent=authorize_request.params.intent,
                        )
                        is None
                    ):
                        return _oauth_error(
                            "invalid_request",
                            "interaction url not configured",
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )

                    state_value = await _authorize_state(
                        provider,
                        authorize_request.oauth_client,
                        authorize_request.params,
                    )
                    secret_oq = _resolve_oauth_query_secret(belgie, settings)
                    login_url = _build_login_with_signed_query(
                        issuer_url=issuer_url,
                        belgie_base_url=belgie.settings.base_url,
                        settings=settings,
                        oauth_client=authorize_request.oauth_client,
                        raw_params=authorize_request.raw_params,
                        params=authorize_request.params,
                        state_key=state_value,
                        secret=secret_oq,
                    )
                    return _redirect_response(request, login_url)
                raise

            params_with_principal = _with_authorization_principal(
                authorize_request.params,
                individual_id=str(individual.id),
                session_id=str(session.id),
            )
            interaction_error = await _resolve_interaction_error(
                provider,
                settings,
                authorize_request.oauth_client,
                params_with_principal,
                prompt_values=authorize_request.prompt_values,
            )
            if interaction_error is not None:
                return _authorize_error(
                    interaction_error.error,
                    interaction_error.description,
                    redirect_uri=authorize_request.redirect_uri,
                    state=params_with_principal.state,
                    issuer_url=issuer_url,
                )

            try:
                interaction = await _resolve_next_interaction(
                    provider,
                    settings,
                    authorize_request.oauth_client,
                    params_with_principal,
                    prompt_values=authorize_request.prompt_values,
                )
            except ValueError as exc:
                return _authorize_error(
                    "invalid_request",
                    str(exc),
                    redirect_uri=authorize_request.redirect_uri,
                    state=params_with_principal.state,
                    issuer_url=issuer_url,
                )
            if interaction is not None:
                interaction_params = replace(params_with_principal, intent=interaction)
                state_value = await _authorize_state(
                    provider,
                    authorize_request.oauth_client,
                    interaction_params,
                )
                secret_oq = _resolve_oauth_query_secret(belgie, settings)
                login_url = _build_login_with_signed_query(
                    issuer_url=issuer_url,
                    belgie_base_url=belgie.settings.base_url,
                    settings=settings,
                    oauth_client=authorize_request.oauth_client,
                    raw_params=authorize_request.raw_params,
                    params=interaction_params,
                    state_key=state_value,
                    secret=secret_oq,
                )
                return _redirect_response(request, login_url)

            state_value = await _authorize_state(provider, authorize_request.oauth_client, params_with_principal)
            redirect_url = await _issue_authorization_code(provider, state_value, issuer_url)
            return _redirect_response(request, redirect_url)

        async def authorize_get_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            return await _authorize(request, client)

        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/authorize", authorize_get_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_token_route(
        router: APIRouter,
        belgie: Belgie,
        engine: BelgieOAuthServerEngine,
        settings: OAuthServer,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        async def token_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> OAuthServerToken | Response:
            if (
                rate_limited := _enforce_rate_limit(
                    request,
                    rate_limiter,
                    "token",
                    settings.rate_limit.token,
                )
            ) is not None:
                return rate_limited
            form = await request.form()
            grant_type = _get_str(form, "grant_type")

            if grant_type is not None and not settings.supports_grant_type(grant_type):
                response: OAuthServerToken | Response = _oauth_error(
                    "unsupported_grant_type",
                    f"unsupported grant_type {grant_type}",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            elif grant_type in {"authorization_code", "refresh_token", "client_credentials"}:
                response = await engine.create_token_response(request, client)
            else:
                response = _oauth_error("unsupported_grant_type", status_code=status.HTTP_400_BAD_REQUEST)

            return response

        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/token",
            token_handler,
            methods=["POST"],
            response_model=OAuthServerToken,
        )
        return router

    @staticmethod
    def _add_register_route(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        async def register_handler(  # noqa: C901, PLR0911
            request: Request,
            response: Response,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> OAuthServerClientRpcResponse | Response:
            if (
                rate_limited := _enforce_rate_limit(
                    request,
                    rate_limiter,
                    "register",
                    settings.rate_limit.registration,
                )
            ) is not None:
                return rate_limited
            if not settings.allow_dynamic_client_registration:
                return _oauth_error(
                    "access_denied",
                    "client registration is disabled",
                    status_code=status.HTTP_403_FORBIDDEN,
                )

            try:
                payload = await request.json()
            except ValueError:
                return _oauth_error(
                    "invalid_request",
                    "invalid JSON body",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if not isinstance(payload, dict):
                return _oauth_error(
                    "invalid_request",
                    "invalid JSON body",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if "skip_consent" in payload:
                return _registration_metadata_error("skip_consent cannot be set during dynamic client registration")

            try:
                metadata = OAuthServerClientMetadata.model_validate(
                    _filter_client_payload_fields(payload, _REGISTER_CLIENT_FIELDS),
                )
            except ValidationError as exc:
                return _registration_validation_error(exc)

            authenticated = False
            authenticated_individual_id: str | None = None
            try:
                user = await client.get_individual(SecurityScopes(), request)
                authenticated = True
                authenticated_individual_id = str(user.id)
            except HTTPException as exc:
                if exc.status_code != status.HTTP_401_UNAUTHORIZED:
                    raise

            if not authenticated and not settings.allow_unauthenticated_client_registration:
                return _oauth_error(
                    "invalid_token",
                    "authentication required for client registration",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            if not authenticated:
                if "client_credentials" in metadata.grant_types:
                    return _registration_metadata_error(
                        "client_credentials grant requires authenticated registration",
                    )
                metadata = _coerce_unauthenticated_registration(metadata)

            try:
                provider.validate_client_metadata(metadata)
                client_info = await provider.register_client(
                    metadata,
                    individual_id=authenticated_individual_id,
                    db=client.db,
                )
            except ValueError as exc:
                description = str(exc) or "invalid client metadata"
                return _registration_metadata_error(description)
            _set_no_store_headers(response)
            return _serialize_oauth_client(client_info, include_secret=True)

        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/register",
            register_handler,
            methods=["POST"],
            status_code=status.HTTP_201_CREATED,
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
        )
        return router

    @staticmethod
    def _add_revoke_route(
        router: APIRouter,
        belgie: Belgie,
        engine: BelgieOAuthServerEngine,
        settings: OAuthServer,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        async def revoke_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
            if (
                rate_limited := _enforce_rate_limit(
                    request,
                    rate_limiter,
                    "revoke",
                    settings.rate_limit.revoke,
                )
            ) is not None:
                return rate_limited
            return await engine.create_revocation_response(request, client)

        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/revoke", revoke_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_userinfo_route(  # noqa: C901, PLR0913
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        issuer_url: str,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        async def userinfo_handler(  # noqa: PLR0911
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> UserInfoResponse | Response:
            if (
                rate_limited := _enforce_rate_limit(
                    request,
                    rate_limiter,
                    "userinfo",
                    settings.rate_limit.userinfo,
                )
            ) is not None:
                return rate_limited
            authorization = request.headers.get("authorization")
            if not authorization:
                return _oauth_error(
                    "invalid_token",
                    "authorization header not found",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            token_value = authorization.removeprefix("Bearer ").strip()
            if not token_value:
                return _oauth_error(
                    "invalid_token",
                    "authorization header not found",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            verified_access_token = await verify_local_access_token(
                provider,
                token_value,
                audience=_oauth_endpoint_url(issuer_url, "userinfo"),
            )
            if verified_access_token is None:
                return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)
            access_token = verified_access_token.token

            if "openid" not in access_token.scopes:
                return _oauth_error("invalid_scope", "Missing required scope", status_code=status.HTTP_400_BAD_REQUEST)

            if access_token.individual_id is None:
                return _oauth_error("invalid_request", "user not found", status_code=status.HTTP_400_BAD_REQUEST)

            try:
                individual_id = UUID(access_token.individual_id)
            except ValueError:
                return _oauth_error("invalid_request", "user not found", status_code=status.HTTP_400_BAD_REQUEST)

            user = await client.adapter.get_individual_by_id(client.db, individual_id)
            if user is None:
                return _oauth_error("invalid_request", "user not found", status_code=status.HTTP_400_BAD_REQUEST)

            oauth_client = await provider.get_client(access_token.client_id)
            if oauth_client is None or oauth_client.disabled:
                return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)
            subject_identifier = (
                provider.resolve_subject_identifier(oauth_client, access_token.individual_id)
                if oauth_client is not None
                else access_token.individual_id
            )
            jwt_payload = await build_access_token_jwt_payload(
                client,
                provider,
                settings,
                issuer_url,
                oauth_client,
                access_token,
                user=user,
            )
            return UserInfoResponse.model_validate(
                {
                    **build_user_claims(
                        user,
                        access_token.scopes,
                        subject_identifier=subject_identifier,
                    ),
                    **(
                        await _resolve_custom_mapping(
                            settings.custom_userinfo_claims,
                            {
                                "user": user,
                                "scopes": list(access_token.scopes),
                                "jwt": jwt_payload,
                            },
                        )
                    ),
                },
            )

        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/userinfo",
            userinfo_handler,
            methods=["GET"],
            response_model=UserInfoResponse,
            response_model_exclude_none=True,
        )
        return router

    @staticmethod
    def _add_end_session_route(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        issuer_url: str,
    ) -> APIRouter:
        async def end_session_handler(  # noqa: C901, PLR0911
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
            id_token_hint = request.query_params.get("id_token_hint")
            if not id_token_hint:
                return _oauth_error("invalid_request", "missing id_token_hint", status_code=status.HTTP_400_BAD_REQUEST)

            # Pass 1: decode without verification only to extract audience and identify
            # the candidate signing secret for full verification in pass 2 below.
            decoded_unverified = _decode_unverified_jwt(id_token_hint)
            if decoded_unverified is None:
                return _oauth_error("invalid_token", "invalid id token", status_code=status.HTTP_401_UNAUTHORIZED)

            requested_client_id = request.query_params.get("client_id")
            if requested_client_id is not None and not _aud_contains(
                decoded_unverified.get("aud"),
                requested_client_id,
            ):
                return _oauth_error("invalid_request", "audience mismatch", status_code=status.HTTP_400_BAD_REQUEST)

            inferred_client_id = requested_client_id or _first_aud(decoded_unverified.get("aud"))
            if not inferred_client_id:
                return _oauth_error(
                    "invalid_request",
                    "id token missing audience",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            oauth_client = await provider.get_client(inferred_client_id)
            if oauth_client is None:
                return _oauth_error("invalid_client", "client doesn't exist", status_code=status.HTTP_400_BAD_REQUEST)
            if oauth_client.enable_end_session is not True:
                return _oauth_error(
                    "invalid_client",
                    "client unable to logout",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
            try:
                # Pass 2: verify signature and standard claims with the server signing config.
                payload = provider.signing_state.decode(
                    id_token_hint,
                    audience=inferred_client_id,
                    issuer=issuer_url,
                    required_claims=["iss", "aud", "exp", "iat", "sub"],
                )
            except JoseError:
                return _oauth_error("invalid_token", "invalid id token", status_code=status.HTTP_401_UNAUTHORIZED)

            sid = payload.get("sid")
            if not isinstance(sid, str) or not sid:
                return _oauth_error(
                    "invalid_request",
                    "id token missing session",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            try:
                session_id = UUID(sid)
            except ValueError:
                return _oauth_error(
                    "invalid_request",
                    "id token missing session",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            await client.sign_out(session_id)

            post_logout_redirect_uri = request.query_params.get("post_logout_redirect_uri")
            state = request.query_params.get("state")
            if post_logout_redirect_uri and oauth_client.post_logout_redirect_uris:
                registered_post_logout_uris = [str(value) for value in oauth_client.post_logout_redirect_uris]
                if post_logout_redirect_uri in registered_post_logout_uris:
                    redirect_uri = construct_redirect_uri(post_logout_redirect_uri, state=state)
                    return _redirect_response(request, redirect_uri)

            return JSONResponse({})

        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/end-session", end_session_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_login_route(
        router: APIRouter,
        belgie: Belgie,
        issuer_url: str,
        settings: OAuthServer,
        provider: SimpleOAuthProvider,
    ) -> APIRouter:
        async def login_handler(request: Request) -> Response:
            query_string = str(request.url.query)
            secret_l = _resolve_oauth_query_secret(belgie, settings)
            if request.query_params.get("sig"):
                if not verify_oauth_query_params(query_string, secret_l):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_signature")
                parsed_l = parse_verified_oauth_query(query_string, secret_l)
                state = (parsed_l or {}).get("state") if parsed_l else None
            else:
                state = request.query_params.get("state")
            if not state:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state")

            state_data = await provider.load_authorization_state(state)
            if state_data is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter")

            login_url = _resolve_auth_redirect_url(
                settings,
                belgie.settings.base_url,
                intent=state_data.intent,
            )
            if login_url is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="interaction url not configured")

            return_to_url = _build_interaction_return_to(issuer_url, state, state_data.intent)
            redirect_url = construct_redirect_uri(login_url, return_to=return_to_url, intent=state_data.intent)
            return _redirect_response(request, redirect_url)

        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/login", login_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_continue_route(
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        issuer_url: str,
    ) -> APIRouter:
        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        async def _handle_continue(
            request: Request,
            client: BelgieClient,
        ) -> Response:
            payload = await _get_request_payload(request)
            state = _state_from_interaction_payload(payload, belgie, settings)

            created = _get_payload_bool(payload, "created")
            selected = _get_payload_bool(payload, "selected")
            post_login = _get_payload_post_login_flag(payload)
            if created is not True and selected is not True and post_login is not True:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing parameters")

            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc
                raise

            handled_prompt: AuthorizePrompt | Literal["post_login"] = (
                "create" if created is True else "select_account" if selected is True else "post_login"
            )

            try:
                await provider.bind_authorization_state(
                    state,
                    individual_id=str(individual.id),
                    session_id=str(session.id),
                )
                redirect_url = await _resume_authorization_flow(
                    provider,
                    settings,
                    state,
                    handled_prompt=handled_prompt,
                    issuer_url=issuer_url,
                    belgie_base_url=belgie.settings.base_url,
                    oauth_query_secret=_resolve_oauth_query_secret(belgie, settings),
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            return _interaction_response(request, redirect_url)

        async def continue_get_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            return await _handle_continue(request, client)

        async def continue_post_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            return await _handle_continue(request, client)

        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/continue", continue_get_handler, methods=["GET"])
        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/continue", continue_post_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_consent_route(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        issuer_url: str,
    ) -> APIRouter:
        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        async def _handle_consent(
            request: Request,
            client: BelgieClient,
        ) -> Response:
            payload = await _get_request_payload(request)
            state = _state_from_interaction_payload(payload, belgie, settings)

            state_data = await provider.load_authorization_state(state)
            if state_data is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter")

            accepted = _get_payload_bool(payload, "accept")
            if accepted is not True:
                redirect_url = _authorize_error_redirect_url(
                    state_data.redirect_uri,
                    error="access_denied",
                    description="User denied access",
                    state=state_data.client_state,
                    issuer_url=issuer_url,
                )
                return _interaction_response(request, redirect_url)

            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc
                raise

            oauth_client = await provider.get_client(state_data.client_id)
            if oauth_client is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_client")

            requested_scopes = parse_scope_param(_get_payload_str(payload, "scope"))
            original_scopes = state_data.scopes or list(settings.default_scopes)
            consent_scopes = requested_scopes or original_scopes
            if not all(scope in original_scopes for scope in consent_scopes):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scope not originally requested")

            try:
                await provider.bind_authorization_state(
                    state,
                    individual_id=str(individual.id),
                    session_id=str(session.id),
                )
                await provider.save_consent(
                    oauth_client.client_id,
                    str(individual.id),
                    consent_scopes,
                    reference_id=await _resolve_consent_reference(
                        settings,
                        oauth_client,
                        AuthorizationParams(
                            state=state,
                            scopes=consent_scopes,
                            code_challenge=state_data.code_challenge,
                            redirect_uri=AnyUrl(state_data.redirect_uri),
                            redirect_uri_provided_explicitly=state_data.redirect_uri_provided_explicitly,
                            resource=state_data.resource,
                            nonce=state_data.nonce,
                            prompt=state_data.prompt,
                            intent=state_data.intent,
                            individual_id=str(individual.id),
                            session_id=str(session.id),
                        ),
                    ),
                )
                await provider.update_authorization_interaction(
                    state,
                    prompt=_remove_prompt_value(state_data.prompt, "consent"),
                    intent="consent",
                    scopes=consent_scopes,
                )
                redirect_url = await _issue_authorization_code(provider, state, issuer_url)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            return _interaction_response(request, redirect_url)

        async def consent_get_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            return await _handle_consent(request, client)

        async def consent_post_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            return await _handle_consent(request, client)

        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/consent", consent_get_handler, methods=["GET"])
        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/consent", consent_post_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_login_callback_route(
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        issuer_url: str,
    ) -> APIRouter:
        async def login_callback_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
            state = request.query_params.get("state")
            if not state:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state")

            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc
                raise

            try:
                await provider.bind_authorization_state(
                    state,
                    individual_id=str(individual.id),
                    session_id=str(session.id),
                )
                state_data = await provider.load_authorization_state(state)
                handled_prompt = "login"
                if state_data is not None and state_data.intent == "create":
                    handled_prompt = "create"
                if state_data is not None and state_data.intent == "post_login":
                    handled_prompt = "post_login"
                redirect_url = await _resume_authorization_flow(
                    provider,
                    settings,
                    state,
                    handled_prompt=handled_prompt,
                    issuer_url=issuer_url,
                    belgie_base_url=belgie.settings.base_url,
                    oauth_query_secret=_resolve_oauth_query_secret(belgie, settings),
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            return _redirect_response(request, redirect_url)

        router.add_api_route(f"{_OAUTH_ENDPOINT_PREFIX}/login/callback", login_callback_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_client_management_routes(  # noqa: C901, PLR0915
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
    ) -> APIRouter:
        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        async def create_client_handler(
            request: Request,
            response: Response,
            client: BelgieClientDep,
        ) -> OAuthServerClientRpcResponse | Response:
            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)
                raise

            try:
                payload = await request.json()
                if not isinstance(payload, dict):
                    model_name = "OAuthServerClientMetadata"
                    raise ValidationError.from_exception_data(model_name, [])
                metadata = OAuthServerClientMetadata.model_validate(
                    _filter_client_payload_fields(payload, _PUBLIC_CLIENT_CREATE_FIELDS),
                )
            except ValidationError as exc:
                return _oauth_error(
                    "invalid_request",
                    _format_validation_error(exc),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            resolved_reference = await _resolve_client_reference_id(settings, str(individual.id), str(session.id))
            reference_id = metadata.reference_id or resolved_reference
            if (
                reference_id is not None
                and reference_id != resolved_reference
                and not await _has_client_privilege(
                    settings,
                    "create",
                    str(individual.id),
                    str(session.id),
                    reference_id,
                )
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            try:
                provider.validate_client_metadata(metadata, allow_confidential_pkce_opt_out=True)
                client_info = await provider.register_client(
                    metadata,
                    individual_id=str(individual.id),
                    reference_id=reference_id,
                    allow_confidential_pkce_opt_out=True,
                    db=client.db,
                )
            except ValueError as exc:
                return _oauth_error("invalid_request", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
            else:
                _set_no_store_headers(response)
                return _serialize_oauth_client(client_info, include_secret=True)

        async def list_clients_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> list[OAuthServerClientRpcResponse] | Response:
            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)
                raise

            individual_id = str(individual.id)
            session_id = str(session.id)
            resolved_reference = await _resolve_client_reference_id(settings, individual_id, session_id)
            requested_reference = request.query_params.get("reference_id")

            if (
                requested_reference is not None
                and requested_reference != resolved_reference
                and not await _has_client_privilege(settings, "list", individual_id, session_id, requested_reference)
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            clients: list[OAuthServerClientInformationFull] = []
            if requested_reference is not None:
                clients = await provider.list_clients(reference_id=requested_reference, db=client.db)
            else:
                clients.extend(await provider.list_clients(individual_id=individual_id, db=client.db))
                if resolved_reference is not None:
                    clients.extend(await provider.list_clients(reference_id=resolved_reference, db=client.db))

            deduped: dict[str, OAuthServerClientInformationFull] = {}
            for oauth_client in clients:
                deduped[oauth_client.client_id] = _redact_client_secret(oauth_client)
            return [_serialize_oauth_client(oauth_client, include_secret=False) for oauth_client in deduped.values()]

        async def prelogin_client_handler(request: Request) -> OAuthServerClientRpcResponse | Response:
            if not settings.allow_public_client_prelogin:
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            payload = await _get_request_payload(request)
            client_id = _get_payload_str(payload, "client_id")
            if client_id is None:
                client_id = _client_id_from_oauth_query(_get_payload_str(payload, "oauth_query"))
            if not client_id:
                return _oauth_error(
                    "invalid_request",
                    "missing client_id",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            oauth_client = await provider.get_client(client_id)
            if oauth_client is None or oauth_client.disabled:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            return _public_client_information(oauth_client)

        async def public_client_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> OAuthServerClientRpcResponse | Response:
            try:
                await client.get_individual(SecurityScopes(), request)
                await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)
                raise
            client_id = request.query_params.get("client_id")
            if not client_id:
                return _oauth_error("invalid_request", "missing client_id", status_code=status.HTTP_400_BAD_REQUEST)
            oauth_client = await provider.get_client(client_id)
            if oauth_client is None or oauth_client.disabled:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            return _public_client_information(oauth_client)

        async def get_client_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> OAuthServerClientRpcResponse | Response:
            client_id = request.query_params.get("client_id")
            if not client_id:
                return _oauth_error("invalid_request", "missing client_id", status_code=status.HTTP_400_BAD_REQUEST)
            oauth_client = await provider.get_client(client_id, db=client.db)
            if oauth_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)

            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_client(
                settings,
                oauth_client,
                action="read",
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            return _serialize_oauth_client(_redact_client_secret(oauth_client), include_secret=False)

        async def update_client_handler(  # noqa: PLR0911
            request: Request,
            client: BelgieClientDep,
        ) -> OAuthServerClientRpcResponse | Response:
            raw_payload = await request.json()
            client_id = raw_payload.get("client_id") if isinstance(raw_payload, dict) else None
            if not isinstance(client_id, str) or not client_id:
                return _oauth_error("invalid_request", "missing client_id", status_code=status.HTTP_400_BAD_REQUEST)
            oauth_client = await provider.get_client(client_id, db=client.db)
            if oauth_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)

            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            individual_id = str(individual.id)
            session_id = str(session.id)
            if not await _can_manage_client(
                settings,
                oauth_client,
                action="update",
                individual_id=individual_id,
                session_id=session_id,
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            payload = (
                raw_payload.get("update")
                if isinstance(raw_payload, dict) and isinstance(raw_payload.get("update"), dict)
                else raw_payload
            )
            if not isinstance(payload, dict):
                return _oauth_error(
                    "invalid_request",
                    "invalid update payload",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            updates = _normalize_client_updates(payload, allowed_fields=_PUBLIC_CLIENT_UPDATE_FIELDS)
            try:
                merged_metadata = _merge_client_metadata(oauth_client, updates)
                provider.validate_client_metadata(
                    merged_metadata.model_copy(update={"skip_consent": None}),
                    allow_confidential_pkce_opt_out=True,
                )
            except (ValidationError, ValueError) as exc:
                description = _format_validation_error(exc) if isinstance(exc, ValidationError) else str(exc)
                return _oauth_error("invalid_request", description, status_code=status.HTTP_400_BAD_REQUEST)
            if "reference_id" in updates:
                new_reference_id = updates["reference_id"]
                resolved_reference = await _resolve_client_reference_id(settings, individual_id, session_id)
                if (
                    isinstance(new_reference_id, str)
                    and new_reference_id != resolved_reference
                    and not await _has_client_privilege(settings, "update", individual_id, session_id, new_reference_id)
                ):
                    return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            try:
                updated_client = await provider.update_client(client_id, updates=updates, db=client.db)
            except ValueError as exc:
                return _oauth_error("invalid_request", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
            if updated_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            return _serialize_oauth_client(_redact_client_secret(updated_client), include_secret=False)

        async def admin_create_client_handler(
            request: Request,
            response: Response,
            client: BelgieClientDep,
        ) -> OAuthServerClientRpcResponse | Response:
            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)
                raise

            try:
                payload = await request.json()
                if not isinstance(payload, dict):
                    model_name = "OAuthServerAdminClientMetadata"
                    raise ValidationError.from_exception_data(model_name, [])
                metadata = OAuthServerAdminClientMetadata.model_validate(
                    _filter_client_payload_fields(payload, _ADMIN_CLIENT_CREATE_FIELDS),
                )
            except ValidationError as exc:
                return _oauth_error(
                    "invalid_request",
                    _format_validation_error(exc),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            resolved_reference = await _resolve_client_reference_id(settings, str(individual.id), str(session.id))
            reference_id = metadata.reference_id or resolved_reference
            if (
                reference_id is not None
                and reference_id != resolved_reference
                and not await _has_client_privilege(
                    settings,
                    "create",
                    str(individual.id),
                    str(session.id),
                    reference_id,
                )
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            try:
                provider.validate_client_metadata(
                    metadata,
                    allow_confidential_pkce_opt_out=True,
                    allow_privileged_fields=True,
                )
                client_info = await provider.register_client(
                    metadata,
                    individual_id=str(individual.id),
                    reference_id=reference_id,
                    allow_confidential_pkce_opt_out=True,
                    db=client.db,
                )
            except ValueError as exc:
                return _oauth_error("invalid_request", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
            else:
                _set_no_store_headers(response)
                return _serialize_oauth_client(client_info, include_secret=True)

        async def admin_update_client_handler(  # noqa: PLR0911
            request: Request,
            client: BelgieClientDep,
        ) -> OAuthServerClientRpcResponse | Response:
            raw_payload = await request.json()
            client_id = raw_payload.get("client_id") if isinstance(raw_payload, dict) else None
            if not isinstance(client_id, str) or not client_id:
                return _oauth_error("invalid_request", "missing client_id", status_code=status.HTTP_400_BAD_REQUEST)
            oauth_client = await provider.get_client(client_id, db=client.db)
            if oauth_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)

            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            individual_id = str(individual.id)
            session_id = str(session.id)
            if not await _can_manage_client(
                settings,
                oauth_client,
                action="update",
                individual_id=individual_id,
                session_id=session_id,
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            payload = (
                raw_payload.get("update")
                if isinstance(raw_payload, dict) and isinstance(raw_payload.get("update"), dict)
                else raw_payload
            )
            if not isinstance(payload, dict):
                return _oauth_error(
                    "invalid_request",
                    "invalid update payload",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            updates = _normalize_client_updates(payload, allowed_fields=_ADMIN_CLIENT_UPDATE_FIELDS)
            try:
                merged_metadata = _merge_client_metadata(oauth_client, updates)
                provider.validate_client_metadata(
                    merged_metadata.model_copy(update={"skip_consent": None}),
                    allow_confidential_pkce_opt_out=True,
                    allow_privileged_fields=True,
                )
            except (ValidationError, ValueError) as exc:
                description = _format_validation_error(exc) if isinstance(exc, ValidationError) else str(exc)
                return _oauth_error("invalid_request", description, status_code=status.HTTP_400_BAD_REQUEST)

            try:
                updated_client = await provider.update_client(client_id, updates=updates, db=client.db)
            except ValueError as exc:
                return _oauth_error("invalid_request", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
            if updated_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            return _serialize_oauth_client(_redact_client_secret(updated_client), include_secret=False)

        async def delete_client_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            payload = await request.json()
            client_id = payload.get("client_id") if isinstance(payload, dict) else None
            if not isinstance(client_id, str) or not client_id:
                return _oauth_error("invalid_request", "missing client_id", status_code=status.HTTP_400_BAD_REQUEST)
            oauth_client = await provider.get_client(client_id, db=client.db)
            if oauth_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)

            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_client(
                settings,
                oauth_client,
                action="delete",
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            try:
                await provider.delete_client(client_id, db=client.db)
            except ValueError as exc:
                return _oauth_error("invalid_request", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
            return JSONResponse({})

        async def rotate_client_secret_handler(
            request: Request,
            response: Response,
            client: BelgieClientDep,
        ) -> OAuthServerClientRpcResponse | Response:
            payload = await request.json()
            client_id = payload.get("client_id") if isinstance(payload, dict) else None
            if not isinstance(client_id, str) or not client_id:
                return _oauth_error("invalid_request", "missing client_id", status_code=status.HTTP_400_BAD_REQUEST)
            oauth_client = await provider.get_client(client_id, db=client.db)
            if oauth_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)

            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_client(
                settings,
                oauth_client,
                action="rotate",
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            try:
                rotated_client = await provider.rotate_client_secret(client_id, db=client.db)
            except ValueError as exc:
                return _oauth_error("invalid_request", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
            if rotated_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            _set_no_store_headers(response)
            return _serialize_oauth_client(rotated_client, include_secret=True)

        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/public-client-prelogin",
            prelogin_client_handler,
            methods=["POST"],
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/public-client",
            public_client_handler,
            methods=["GET"],
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            f"/admin{_OAUTH_ENDPOINT_PREFIX}/create-client",
            admin_create_client_handler,
            methods=["POST"],
            status_code=status.HTTP_201_CREATED,
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
            include_in_schema=False,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/create-client",
            create_client_handler,
            methods=["POST"],
            status_code=status.HTTP_201_CREATED,
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/get-clients",
            list_clients_handler,
            methods=["GET"],
            response_model=list[OAuthServerClientRpcResponse],
            response_model_exclude_none=True,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/get-client",
            get_client_handler,
            methods=["GET"],
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            f"/admin{_OAUTH_ENDPOINT_PREFIX}/update-client",
            admin_update_client_handler,
            methods=["PATCH", "POST"],
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
            include_in_schema=False,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/update-client",
            update_client_handler,
            methods=["POST"],
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/delete-client",
            delete_client_handler,
            methods=["POST"],
            response_model=None,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/client/rotate-secret",
            rotate_client_secret_handler,
            methods=["POST"],
            response_model=OAuthServerClientRpcResponse,
            response_model_exclude_none=True,
        )
        return router

    @staticmethod
    def _add_consent_management_routes(  # noqa: C901, PLR0915
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
    ) -> APIRouter:
        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        async def list_consents_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> list[OAuthServerConsentRpcResponse] | Response:
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            individual_id = str(individual.id)
            session_id = str(session.id)
            requested_reference = request.query_params.get("reference_id")
            resolved_reference = await _resolve_client_reference_id(settings, individual_id, session_id)
            if (
                requested_reference is not None
                and requested_reference != resolved_reference
                and not await _has_client_privilege(settings, "list", individual_id, session_id, requested_reference)
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            consents = await provider.list_consents(
                individual_id,
                reference_id=requested_reference,
                db=client.db,
            )
            return [_serialize_consent(consent) for consent in consents]

        async def get_consent_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> OAuthServerConsentRpcResponse | Response:
            consent_id_raw = request.query_params.get("id")
            if not consent_id_raw:
                return _oauth_error("not_found", "missing id parameter", status_code=status.HTTP_404_NOT_FOUND)
            try:
                consent_id = UUID(consent_id_raw)
            except ValueError:
                return _oauth_error("not_found", "missing id parameter", status_code=status.HTTP_404_NOT_FOUND)
            consent = await provider.get_consent_by_id(consent_id, db=client.db)
            if consent is None:
                return _oauth_error("not_found", "no consent", status_code=status.HTTP_404_NOT_FOUND)
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_consent(
                settings,
                consent,
                action="read",
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            return _serialize_consent(consent)

        async def update_consent_handler(  # noqa: C901, PLR0911
            request: Request,
            client: BelgieClientDep,
        ) -> OAuthServerConsentRpcResponse | Response:
            payload = await request.json()
            consent_id_raw = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(consent_id_raw, str) or not consent_id_raw:
                return _oauth_error("not_found", "missing id parameter", status_code=status.HTTP_404_NOT_FOUND)
            try:
                consent_id = UUID(consent_id_raw)
            except ValueError:
                return _oauth_error("not_found", "missing id parameter", status_code=status.HTTP_404_NOT_FOUND)
            existing_consent = await provider.get_consent_by_id(consent_id, db=client.db)
            if existing_consent is None:
                return _oauth_error("not_found", "no consent", status_code=status.HTTP_404_NOT_FOUND)
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_consent(
                settings,
                existing_consent,
                action="update",
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            updates = None
            if isinstance(payload, dict):
                raw_updates = payload.get("update")
                if isinstance(raw_updates, dict):
                    updates = raw_updates
            scopes = updates.get("scopes") if isinstance(updates, dict) else None
            if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
                return _oauth_error(
                    "invalid_request",
                    "scopes must be provided",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            oauth_client = await provider.get_client(existing_consent.client_id, db=client.db)
            if oauth_client is None:
                return _oauth_error("invalid_client", status_code=status.HTTP_400_BAD_REQUEST)
            try:
                provider.validate_scopes_for_client(oauth_client, list(scopes))
            except ValueError as exc:
                return _oauth_error("invalid_scope", str(exc), status_code=status.HTTP_400_BAD_REQUEST)
            updated_consent = await provider.update_consent(consent_id, scopes=list(scopes), db=client.db)
            if updated_consent is None:
                return _oauth_error("not_found", "no consent", status_code=status.HTTP_404_NOT_FOUND)
            return _serialize_consent(updated_consent)

        async def delete_consent_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            payload = await request.json()
            consent_id_raw = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(consent_id_raw, str) or not consent_id_raw:
                return _oauth_error("not_found", "missing id parameter", status_code=status.HTTP_404_NOT_FOUND)
            try:
                consent_id = UUID(consent_id_raw)
            except ValueError:
                return _oauth_error("not_found", "missing id parameter", status_code=status.HTTP_404_NOT_FOUND)
            existing_consent = await provider.get_consent_by_id(consent_id, db=client.db)
            if existing_consent is None:
                return _oauth_error("not_found", "no consent", status_code=status.HTTP_404_NOT_FOUND)
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_consent(
                settings,
                existing_consent,
                action="delete",
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            await provider.delete_consent(consent_id, db=client.db)
            return JSONResponse({})

        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/get-consents",
            list_consents_handler,
            methods=["GET"],
            response_model=list[OAuthServerConsentRpcResponse],
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/get-consent",
            get_consent_handler,
            methods=["GET"],
            response_model=OAuthServerConsentRpcResponse,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/update-consent",
            update_consent_handler,
            methods=["POST"],
            response_model=OAuthServerConsentRpcResponse,
        )
        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/delete-consent",
            delete_consent_handler,
            methods=["POST"],
            response_model=None,
        )
        return router

    @staticmethod
    def _add_introspect_route(
        router: APIRouter,
        belgie: Belgie,
        engine: BelgieOAuthServerEngine,
        settings: OAuthServer,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        async def introspect_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> OAuthServerIntrospectionResponse | Response:
            if (
                rate_limited := _enforce_rate_limit(
                    request,
                    rate_limiter,
                    "introspect",
                    settings.rate_limit.introspect,
                )
            ) is not None:
                return rate_limited
            return await engine.create_introspection_response(request, client)

        router.add_api_route(
            f"{_OAUTH_ENDPOINT_PREFIX}/introspect",
            introspect_handler,
            methods=["POST"],
            response_model=OAuthServerIntrospectionResponse,
            response_model_exclude_none=True,
        )
        return router


def _build_issuer_url(belgie: Belgie, _settings: OAuthServer) -> str:
    parsed = urlparse(belgie.settings.base_url)
    base_path = parsed.path.rstrip("/")
    auth_path = "auth"
    full_path = f"{base_path}/{auth_path}" if base_path else f"/{auth_path}"
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))


async def _parse_authorize_request(  # noqa: C901, PLR0911
    data: dict[str, str],
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    _belgie_base_url: str,
    issuer_url: str,
) -> _AuthorizeRequestContext | Response:
    resolved_data = await _resolve_request_uri_params(data, settings)
    if resolved_data is None:
        return _oauth_error("invalid_request_uri", "request_uri is invalid or expired")

    response_type = _get_str(resolved_data, "response_type")
    if response_type != "code":
        return _oauth_error("unsupported_response_type", status_code=status.HTTP_400_BAD_REQUEST)

    client_id = _get_str(resolved_data, "client_id")
    if not client_id:
        return _oauth_error("invalid_request", "missing client_id", status_code=status.HTTP_400_BAD_REQUEST)

    oauth_client = await provider.get_client(client_id)
    if not oauth_client or oauth_client.disabled:
        return _oauth_error("invalid_client", status_code=status.HTTP_400_BAD_REQUEST)

    redirect_uri_raw = _get_str(resolved_data, "redirect_uri")
    redirect_uri = AnyUrl(redirect_uri_raw) if redirect_uri_raw else None
    try:
        validated_redirect_uri = _validate_authorize_redirect_uri(oauth_client, redirect_uri)
    except InvalidRedirectUriError as exc:
        return _oauth_error("invalid_request", exc.message, status_code=status.HTTP_400_BAD_REQUEST)

    redirect_uri_string = str(validated_redirect_uri)
    prompt_values, prompt_error = _parse_prompt_values(_get_str(resolved_data, "prompt"))
    if prompt_error is not None:
        return _authorize_error(
            "invalid_request",
            prompt_error,
            redirect_uri=redirect_uri_string,
            state=_get_str(resolved_data, "state"),
            issuer_url=issuer_url,
        )
    if "select_account" in prompt_values and settings.select_account_url is None:
        return _authorize_error(
            "invalid_request",
            "unsupported prompt type",
            redirect_uri=redirect_uri_string,
            state=_get_str(resolved_data, "state"),
            issuer_url=issuer_url,
        )

    scope_raw = _get_str(resolved_data, "scope")
    requested_scopes = parse_scope_param(scope_raw)
    if requested_scopes is not None and not requested_scopes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing scope")
    if requested_scopes is None:
        scopes = provider.default_scopes_for_client(oauth_client)
    else:
        try:
            provider.validate_scopes_for_client(oauth_client, requested_scopes)
        except ValueError as exc:
            return _authorize_error(
                "invalid_scope",
                str(exc),
                redirect_uri=redirect_uri_string,
                state=_get_str(resolved_data, "state"),
                issuer_url=issuer_url,
            )
        scopes = requested_scopes

    code_challenge = _get_str(resolved_data, "code_challenge")
    code_challenge_method_value = _get_str(resolved_data, "code_challenge_method")
    pkce_error = validate_pkce_inputs(oauth_client, scopes, code_challenge, code_challenge_method_value)
    if pkce_error is not None:
        return _authorize_error(
            "invalid_request",
            pkce_error,
            redirect_uri=redirect_uri_string,
            state=_get_str(resolved_data, "state"),
            issuer_url=issuer_url,
        )

    prompt = _normalize_prompt_values(prompt_values)

    params = AuthorizationParams(
        state=_get_str(resolved_data, "state") or None,
        scopes=scopes,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method_value,
        redirect_uri=validated_redirect_uri,
        redirect_uri_provided_explicitly=redirect_uri_raw is not None,
        resource=None,
        nonce=_get_str(resolved_data, "nonce"),
        prompt=prompt,
        intent=_derive_initial_intent(prompt_values),
    )
    raw_params = {str(k): str(v) for k, v in resolved_data.items()}
    return _AuthorizeRequestContext(
        oauth_client=oauth_client,
        params=params,
        prompt_values=prompt_values,
        redirect_uri=redirect_uri_string,
        raw_params=raw_params,
    )


async def _authorize_state(
    provider: SimpleOAuthProvider,
    oauth_client: OAuthServerClientInformationFull,
    params: AuthorizationParams,
) -> str:
    try:
        return await provider.authorize(oauth_client, params)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _issue_authorization_code(provider: SimpleOAuthProvider, state: str, issuer_url: str) -> str:
    try:
        return await provider.issue_authorization_code(state, issuer=issuer_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _oauth_endpoint_url(issuer_url: str, path: str) -> str:
    return join_url(issuer_url, f"oauth2/{path}")


def _resolve_auth_redirect_url(
    settings: OAuthServer,
    belgie_base_url: str,
    *,
    intent: OAuthServerLoginIntent,
) -> str | None:
    if intent == "consent":
        return _resolve_redirect_url(belgie_base_url, settings.consent_url) if settings.consent_url else None
    if intent == "select_account":
        return (
            _resolve_redirect_url(belgie_base_url, settings.select_account_url) if settings.select_account_url else None
        )
    if intent == "post_login":
        return _resolve_redirect_url(belgie_base_url, settings.post_login_url) if settings.post_login_url else None
    if intent == "create" and settings.signup_url:
        return _resolve_redirect_url(belgie_base_url, settings.signup_url)
    if settings.login_url:
        return _resolve_redirect_url(belgie_base_url, settings.login_url)
    return None


def _resolve_redirect_url(belgie_base_url: str, redirect_url: str) -> str:
    parsed_redirect_url = urlparse(redirect_url)
    if parsed_redirect_url.scheme in {"http", "https"}:
        return redirect_url
    return join_url(belgie_base_url, redirect_url)


async def _resolve_request_uri_params(
    data: dict[str, str],
    settings: OAuthServer,
) -> dict[str, str] | None:
    request_uri = _get_str(data, "request_uri")
    if request_uri is None:
        return data
    if settings.request_uri_resolver is None:
        return None

    client_id = _get_str(data, "client_id") or ""
    resolved = settings.request_uri_resolver(request_uri, client_id)
    if inspect.isawaitable(resolved):
        resolved = await resolved
    if resolved is None:
        return None

    resolved_data = dict(resolved)
    if client_id:
        resolved_data["client_id"] = client_id
    return resolved_data


def _authorize_error(  # noqa: PLR0913
    error: str,
    description: str | None = None,
    *,
    redirect_uri: str | None = None,
    state: str | None = None,
    issuer_url: str | None = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    if redirect_uri is None:
        return _oauth_error(error, description, status_code=status_code)
    redirect_url = _authorize_error_redirect_url(
        redirect_uri,
        error=error,
        description=description,
        state=state,
        issuer_url=issuer_url,
    )
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


def _authorize_error_redirect_url(
    redirect_uri: str,
    *,
    error: str,
    description: str | None = None,
    state: str | None = None,
    issuer_url: str | None = None,
) -> str:
    return construct_redirect_uri(
        redirect_uri,
        error=error,
        error_description=description,
        state=state,
        iss=issuer_url,
    )


def _parse_prompt_values(prompt: str | None) -> tuple[frozenset[AuthorizePrompt], str | None]:
    if prompt is None:
        return frozenset(), None

    prompt_values: list[AuthorizePrompt] = []
    for raw_value in prompt.split(" "):
        if not raw_value:
            continue
        if raw_value not in {"none", "consent", "login", "create", "select_account"}:
            return frozenset(), "unsupported prompt value"
        typed_value = raw_value
        if typed_value not in prompt_values:
            prompt_values.append(typed_value)

    return frozenset(prompt_values), None


def _normalize_prompt_values(prompt_values: frozenset[AuthorizePrompt]) -> str | None:
    if not prompt_values:
        return None
    ordered_values = [
        prompt for prompt in ("none", "login", "consent", "create", "select_account") if prompt in prompt_values
    ]
    return " ".join(ordered_values)


def _derive_initial_intent(prompt_values: frozenset[AuthorizePrompt]) -> OAuthServerLoginIntent:
    if "create" in prompt_values:
        return "create"
    return "login"


def _validate_authorize_redirect_uri(
    oauth_client: OAuthServerClientInformationFull,
    redirect_uri: AnyUrl | None,
) -> AnyUrl:
    try:
        return oauth_client.validate_redirect_uri(redirect_uri)
    except InvalidRedirectUriError:
        if redirect_uri is None or not oauth_client_is_public(oauth_client) or oauth_client.redirect_uris is None:
            raise

        redirect_uri_str = str(redirect_uri)
        if any(
            redirect_uris_match(str(registered_redirect_uri), redirect_uri_str)
            for registered_redirect_uri in oauth_client.redirect_uris
        ):
            return redirect_uri
        raise


async def _resolve_interaction_error(  # noqa: PLR0911, PLR0913
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    params: AuthorizationParams,
    *,
    prompt_values: frozenset[AuthorizePrompt],
    allow_select_account_resolver: bool = True,
) -> _InteractionError | None:
    if "none" not in prompt_values:
        return None
    if params.individual_id is None:
        return _InteractionError(error="login_required", description="authentication required")
    if allow_select_account_resolver and await _select_account_required(settings, oauth_client, params):
        return _InteractionError(
            error="account_selection_required",
            description="End-User account selection is required",
        )
    if "select_account" in prompt_values:
        return _InteractionError(
            error="account_selection_required",
            description="End-User account selection is required",
        )
    if await _post_login_required(settings, oauth_client, params):
        return _InteractionError(
            error="interaction_required",
            description="End-User interaction is required",
        )
    if "consent" in prompt_values:
        return _InteractionError(error="consent_required", description="End-User consent is required")
    if await _consent_required(provider, settings, oauth_client, params):
        return _InteractionError(error="consent_required", description="End-User consent is required")
    return None


async def _resolve_next_interaction(  # noqa: C901, PLR0911, PLR0913
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    params: AuthorizationParams,
    *,
    prompt_values: frozenset[AuthorizePrompt],
    allow_select_account_resolver: bool = True,
) -> OAuthServerLoginIntent | None:
    if params.individual_id is None or params.session_id is None:
        return params.intent
    if "select_account" in prompt_values:
        if settings.select_account_url is None:
            msg = "unsupported prompt type"
            raise ValueError(msg)
        return "select_account"
    if allow_select_account_resolver and await _select_account_required(settings, oauth_client, params):
        if settings.select_account_url is None:
            msg = "unsupported prompt type"
            raise ValueError(msg)
        return "select_account"
    if await _post_login_required(settings, oauth_client, params):
        if settings.post_login_url is None:
            msg = "post_login_url not configured"
            raise ValueError(msg)
        return "post_login"
    if "consent" in prompt_values:
        if settings.consent_url is None:
            msg = "consent_url not configured"
            raise ValueError(msg)
        return "consent"
    if await _consent_required(provider, settings, oauth_client, params):
        if settings.consent_url is None:
            msg = "consent_url not configured"
            raise ValueError(msg)
        return "consent"
    return None


async def _consent_required(
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    params: AuthorizationParams,
) -> bool:
    if params.individual_id is None:
        return False
    if await settings.is_trusted_client(oauth_client):
        return False
    reference_id = await _resolve_consent_reference(settings, oauth_client, params)
    return not await provider.has_consent(
        oauth_client.client_id,
        params.individual_id,
        params.scopes or list(settings.default_scopes),
        reference_id=reference_id,
    )


async def _select_account_required(
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    params: AuthorizationParams,
) -> bool:
    if settings.select_account_resolver is None:
        return False
    if params.individual_id is None or params.session_id is None:
        return False

    should_select = settings.select_account_resolver(
        oauth_client.client_id,
        params.individual_id,
        params.session_id,
        params.scopes or list(settings.default_scopes),
    )
    if inspect.isawaitable(should_select):
        should_select = await should_select
    return should_select is True


async def _post_login_required(
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    params: AuthorizationParams,
) -> bool:
    if settings.post_login_resolver is None:
        return False
    if params.individual_id is None or params.session_id is None:
        return False

    should_redirect = settings.post_login_resolver(
        oauth_client.client_id,
        params.individual_id,
        params.session_id,
        params.scopes or list(settings.default_scopes),
    )
    if inspect.isawaitable(should_redirect):
        should_redirect = await should_redirect
    return should_redirect is True


async def _resolve_consent_reference(
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    params: AuthorizationParams,
) -> str | None:
    if settings.consent_reference_resolver is None:
        return None
    if params.individual_id is None or params.session_id is None:
        return None

    resolved_reference = settings.consent_reference_resolver(
        oauth_client.client_id,
        params.individual_id,
        params.session_id,
        params.scopes or list(settings.default_scopes),
    )
    if inspect.isawaitable(resolved_reference):
        resolved_reference = await resolved_reference
    return resolved_reference


async def _resume_authorization_flow(  # noqa: PLR0913
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    state: str,
    *,
    handled_prompt: AuthorizePrompt | Literal["post_login"],
    issuer_url: str,
    belgie_base_url: str,
    oauth_query_secret: str,
) -> str:
    state_data = await provider.load_authorization_state(state)
    if state_data is None:
        msg = "Invalid state parameter"
        raise ValueError(msg)

    oauth_client = await provider.get_client(state_data.client_id)
    if oauth_client is None:
        msg = "invalid_client"
        raise ValueError(msg)

    updated_prompt = _remove_prompt_value(state_data.prompt, handled_prompt)
    updated_prompt_values, prompt_error = _parse_prompt_values(updated_prompt)
    if prompt_error is not None:
        raise ValueError(prompt_error)

    await provider.update_authorization_interaction(
        state,
        prompt=updated_prompt,
        intent="login",
    )

    params = AuthorizationParams(
        state=state,
        scopes=state_data.scopes,
        code_challenge=state_data.code_challenge,
        code_challenge_method=None,
        redirect_uri=AnyUrl(state_data.redirect_uri),
        redirect_uri_provided_explicitly=state_data.redirect_uri_provided_explicitly,
        resource=state_data.resource,
        nonce=state_data.nonce,
        prompt=updated_prompt,
        intent="login",
        individual_id=state_data.individual_id,
        session_id=state_data.session_id,
    )

    interaction = await _resolve_next_interaction(
        provider,
        settings,
        oauth_client,
        params,
        prompt_values=updated_prompt_values,
        allow_select_account_resolver=False,
    )
    if interaction is not None:
        await provider.update_authorization_interaction(
            state,
            prompt=updated_prompt,
            intent=interaction,
        )
        return _build_resume_login_with_signed_query(
            issuer_url=issuer_url,
            belgie_base_url=belgie_base_url,
            settings=settings,
            state_key=state,
            state_data=state_data,
            secret=oauth_query_secret,
            intent=interaction,
        )

    return await _issue_authorization_code(provider, state, issuer_url)


def _remove_prompt_value(prompt: str | None, value: AuthorizePrompt) -> str | None:
    prompt_values, prompt_error = _parse_prompt_values(prompt)
    if prompt_error is not None or not prompt_values:
        return None
    remaining_values = frozenset(existing for existing in prompt_values if existing != value)
    return _normalize_prompt_values(remaining_values)


def _build_interaction_return_to(issuer_url: str, state: str, intent: OAuthServerLoginIntent) -> str:
    if intent == "create":
        return construct_redirect_uri(_oauth_endpoint_url(issuer_url, "continue"), state=state, created="true")
    if intent == "select_account":
        return construct_redirect_uri(_oauth_endpoint_url(issuer_url, "continue"), state=state, selected="true")
    if intent == "post_login":
        return construct_redirect_uri(_oauth_endpoint_url(issuer_url, "continue"), state=state, post_login="true")
    if intent == "consent":
        return construct_redirect_uri(_oauth_endpoint_url(issuer_url, "consent"), state=state)
    return construct_redirect_uri(_oauth_endpoint_url(issuer_url, "login/callback"), state=state)


def _oauth_error(
    error: str,
    description: str | None = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> JSONResponse:
    return JSONResponse(
        OAuthServerErrorResponse(
            error=error,
            error_description=description,
        ).model_dump(mode="json", exclude_none=True),
        status_code=status_code,
    )


def _rate_limited_error(retry_after: int | None) -> JSONResponse:
    response = _oauth_error(
        "rate_limited",
        "too many requests",
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


def _request_identifier(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _enforce_rate_limit(
    request: Request,
    rate_limiter: OAuthServerRateLimiter,
    bucket: str,
    rule: object,
) -> Response | None:
    if rule is None:
        return None
    allowed, retry_after = rate_limiter.check(bucket, _request_identifier(request), rule)
    if allowed:
        return None
    return _rate_limited_error(retry_after)


def _redirect_response(request: Request, url: str, *, status_code: int = status.HTTP_302_FOUND) -> Response:
    if is_fetch_request(request):
        return JSONResponse({"redirect": True, "url": url, "redirect_to": url, "redirect_url": url})
    return RedirectResponse(url=url, status_code=status_code)


def _set_no_store_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _format_validation_error(error: ValidationError) -> str:
    entries = error.errors()
    if not entries:
        return "invalid client metadata"
    entry = entries[0]
    loc = ".".join(str(part) for part in entry.get("loc", []) if part is not None)
    msg = entry.get("msg", "invalid client metadata")
    if loc:
        return f"{loc}: {msg}"
    return msg


def _coerce_unauthenticated_registration(
    metadata: OAuthServerClientMetadata,
) -> OAuthServerClientMetadata:
    return metadata.model_copy(
        update={
            "token_endpoint_auth_method": "none",
            "type": None if metadata.type == "web" else metadata.type,
        },
    )


def _registration_validation_error(error: ValidationError) -> JSONResponse:
    description = _format_validation_error(error)
    if any("redirect_uris" in ".".join(str(part) for part in entry.get("loc", [])) for entry in error.errors()):
        return _oauth_error(
            "invalid_redirect_uri",
            description,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return _oauth_error(
        "invalid_client_metadata",
        description,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _registration_metadata_error(description: str) -> JSONResponse:
    error = "invalid_client_metadata"
    if description.startswith("unsupported token_endpoint_auth_method: "):
        error = "invalid_request"
    elif description.startswith("cannot request scope "):
        error = "invalid_scope"
    elif "redirect_uri" in description.lower():
        error = "invalid_redirect_uri"
    return _oauth_error(error, description, status_code=status.HTTP_400_BAD_REQUEST)


async def _get_request_params(request: Request) -> dict[str, str]:
    if request.method == "GET":
        return dict(request.query_params)
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items() if isinstance(value, str)}
    form = await request.form()
    return {key: value for key, value in form.items() if isinstance(value, str)}


async def _get_request_payload(request: Request) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = dict(request.query_params)
    if request.method == "GET":
        return payload
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
        if isinstance(body, dict):
            payload |= {key: value for key, value in body.items() if isinstance(key, str)}
        return payload
    form = await request.form()
    payload |= {key: value for key, value in form.items() if isinstance(value, str)}
    return payload


def _get_str(data: FormInput, key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return None


def _get_payload_str(payload: Mapping[str, JSONValue], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return None


def _get_payload_bool(payload: Mapping[str, JSONValue], key: str) -> bool | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    return None


def _client_id_from_oauth_query(oauth_query: str | None) -> str | None:
    if not oauth_query:
        return None
    parsed_query = dict(parse_qsl(oauth_query, keep_blank_values=True))
    client_id = parsed_query.get("client_id")
    return client_id if isinstance(client_id, str) and client_id else None


def _filter_client_payload_fields(
    payload: Mapping[str, JSONValue],
    allowed_fields: frozenset[str],
) -> dict[str, JSONValue]:
    return {key: value for key, value in payload.items() if key in allowed_fields}


def _json_value_or_none(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [converted for item in value if (converted := _json_value_or_none(item)) is not None]
    if isinstance(value, dict):
        return {
            str(key): converted for key, item in value.items() if (converted := _json_value_or_none(item)) is not None
        }
    return None


async def _resolve_custom_mapping(
    resolver: Callable[[dict[str, object]], dict[str, object] | Awaitable[dict[str, object]]] | None,
    payload: dict[str, object],
) -> dict[str, object]:
    if resolver is None:
        return {}
    resolved = resolver(payload)
    custom_payload = await resolved if inspect.isawaitable(resolved) else resolved
    return dict(custom_payload or {})


async def _resolve_client_reference_id(
    settings: OAuthServer,
    individual_id: str,
    session_id: str,
) -> str | None:
    if settings.client_reference_resolver is None:
        return None
    resolved_reference = settings.client_reference_resolver(individual_id, session_id)
    if inspect.isawaitable(resolved_reference):
        resolved_reference = await resolved_reference
    return resolved_reference


async def _has_client_privilege(
    settings: OAuthServer,
    action: Literal["create", "read", "update", "delete", "list", "rotate"],
    individual_id: str,
    session_id: str,
    reference_id: str | None,
) -> bool:
    if settings.client_privileges is None:
        return False
    allowed = settings.client_privileges(action, individual_id, session_id, reference_id)
    if inspect.isawaitable(allowed):
        allowed = await allowed
    return allowed is True


async def _can_manage_client(
    settings: OAuthServer,
    oauth_client: OAuthServerClientInformationFull,
    *,
    action: Literal["read", "update", "delete", "rotate"],
    individual_id: str,
    session_id: str,
) -> bool:
    if await _has_client_privilege(settings, action, individual_id, session_id, oauth_client.reference_id):
        return True
    if oauth_client.individual_id is not None and oauth_client.individual_id == individual_id:
        return True
    if oauth_client.reference_id is None:
        return False
    return oauth_client.reference_id == await _resolve_client_reference_id(settings, individual_id, session_id)


def _redact_client_secret(client_info: OAuthServerClientInformationFull) -> OAuthServerClientInformationFull:
    return client_info.model_copy(update={"client_secret": None})


def _serialize_oauth_client(
    client_info: OAuthServerClientInformationFull,
    *,
    include_secret: bool,
) -> OAuthServerClientRpcResponse:
    metadata = (
        {
            key: value
            for key, value in (client_info.metadata_json or {}).items()
            if _json_value_or_none(value) is not None
        }
        if client_info.metadata_json is not None
        else {}
    )
    payload: dict[str, JSONValue] = {
        **metadata,
        "client_id": client_info.client_id,
        "client_secret_expires_at": client_info.client_secret_expires_at,
        "scope": client_info.scope,
        "user_id": client_info.individual_id,
        "client_id_issued_at": client_info.client_id_issued_at,
        "client_name": client_info.client_name,
        "client_uri": str(client_info.client_uri) if client_info.client_uri is not None else None,
        "logo_uri": str(client_info.logo_uri) if client_info.logo_uri is not None else None,
        "contacts": client_info.contacts,
        "tos_uri": str(client_info.tos_uri) if client_info.tos_uri is not None else None,
        "policy_uri": str(client_info.policy_uri) if client_info.policy_uri is not None else None,
        "software_id": client_info.software_id,
        "software_version": client_info.software_version,
        "software_statement": client_info.software_statement,
        "redirect_uris": [str(uri) for uri in client_info.redirect_uris or []],
        "post_logout_redirect_uris": (
            [str(uri) for uri in client_info.post_logout_redirect_uris]
            if client_info.post_logout_redirect_uris is not None
            else None
        ),
        "token_endpoint_auth_method": client_info.token_endpoint_auth_method,
        "grant_types": client_info.grant_types,
        "response_types": client_info.response_types,
        "public": oauth_client_is_public(client_info),
        "type": client_info.type,
        "disabled": client_info.disabled,
        "skip_consent": client_info.skip_consent,
        "enable_end_session": client_info.enable_end_session,
        "require_pkce": client_info.require_pkce,
        "subject_type": client_info.subject_type,
        "reference_id": client_info.reference_id,
    }
    if include_secret and client_info.client_secret is not None:
        payload["client_secret"] = client_info.client_secret
    filtered = {key: value for key, value in payload.items() if value is not None}
    return OAuthServerClientRpcResponse.model_validate(filtered)


def _public_client_information(client_info: OAuthServerClientInformationFull) -> OAuthServerClientRpcResponse:
    payload = _serialize_oauth_client(client_info, include_secret=False).model_dump(exclude_none=True, mode="json")
    if not isinstance(payload, dict):
        msg = "unexpected client record payload"
        raise TypeError(msg)
    allowed = {"client_id", "client_name", "client_uri", "logo_uri", "contacts", "tos_uri", "policy_uri"}
    return OAuthServerClientRpcResponse.model_validate({key: value for key, value in payload.items() if key in allowed})


def _serialize_consent(consent: _ConsentLike) -> OAuthServerConsentRpcResponse:
    created_at = consent.created_at
    created_at_timestamp = int(created_at.timestamp()) if isinstance(created_at, datetime) else int(created_at)
    return OAuthServerConsentRpcResponse(
        id=str(consent.id),
        client_id=consent.client_id,
        user_id=consent.individual_id,
        reference_id=consent.reference_id,
        scopes=list(consent.scopes),
        created_at=created_at_timestamp,
    )


async def _can_manage_consent(
    settings: OAuthServer,
    consent: _ConsentLike,
    *,
    action: Literal["read", "update", "delete"],
    individual_id: str,
    session_id: str,
) -> bool:
    reference_id = consent.reference_id
    if await _has_client_privilege(settings, action, individual_id, session_id, reference_id):
        return True
    if consent.individual_id != individual_id:
        return False
    if reference_id is None:
        return True
    return reference_id == await _resolve_client_reference_id(settings, individual_id, session_id)


def _normalize_client_updates(
    payload: Mapping[str, JSONValue],
    *,
    allowed_fields: frozenset[str],
) -> dict[str, JSONValue]:
    list_fields = {"redirect_uris", "post_logout_redirect_uris", "contacts", "grant_types", "response_types"}
    string_fields = {
        "token_endpoint_auth_method",
        "scope",
        "client_name",
        "client_uri",
        "logo_uri",
        "tos_uri",
        "policy_uri",
        "software_id",
        "software_version",
        "software_statement",
        "type",
        "subject_type",
        "reference_id",
        "client_secret_expires_at",
    }
    bool_fields = {"disabled", "skip_consent", "require_pkce", "enable_end_session"}
    dict_fields = {"metadata", "metadata_json"}

    normalized: dict[str, JSONValue] = {}
    for key, value in payload.items():
        if key not in allowed_fields:
            continue
        if key in list_fields and isinstance(value, list):
            normalized[key] = [str(item) for item in value if isinstance(item, str)]
        elif (
            (key in string_fields and (value is None or isinstance(value, str)))
            or (key == "client_secret_expires_at" and (value is None or isinstance(value, (str, int))))
            or (key in bool_fields and (value is None or isinstance(value, bool)))
            or (key in dict_fields and (value is None or isinstance(value, dict)))
        ):
            normalized["metadata_json" if key == "metadata" else key] = value
    return normalized


def _merge_client_metadata(
    oauth_client: OAuthServerClientInformationFull,
    updates: Mapping[str, JSONValue],
) -> OAuthServerClientMetadata:
    base = OAuthServerClientMetadata.model_validate(oauth_client)
    field_names = set(OAuthServerClientMetadata.model_fields)
    merged = {**base.model_dump(), **{k: v for k, v in updates.items() if k in field_names}}
    return OAuthServerClientMetadata.model_validate(merged)


def _with_authorization_principal(
    params: AuthorizationParams,
    *,
    individual_id: str,
    session_id: str,
) -> AuthorizationParams:
    return replace(
        params,
        individual_id=individual_id,
        session_id=session_id,
    )


def _decode_unverified_jwt(token: str) -> dict[str, JSONValue] | None:
    try:
        payload = json.loads(jws.extract_compact(to_bytes(token)).payload)
    except (JoseError, TypeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def _aud_contains(aud: JSONValue, value: str) -> bool:
    if isinstance(aud, str):
        return aud == value
    if isinstance(aud, list):
        return any(entry == value for entry in aud if isinstance(entry, str))
    return False


def _first_aud(aud: JSONValue) -> str | None:
    if isinstance(aud, str):
        return aud
    if isinstance(aud, list) and aud:
        first = aud[0]
        if isinstance(first, str):
            return first
    return None
