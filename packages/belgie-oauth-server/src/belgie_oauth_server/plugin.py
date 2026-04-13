import base64
import binascii
import inspect
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, Literal, Protocol, cast
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import jwt
from belgie_core.core.belgie import Belgie
from belgie_core.core.client import BelgieClient
from belgie_core.core.exceptions import OAuthError
from belgie_core.core.plugin import PluginClient
from belgie_core.core.settings import BelgieSettings
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import SecurityScopes
from jwt import InvalidTokenError
from pydantic import AnyUrl, ValidationError
from starlette.datastructures import FormData

from belgie_oauth_server.client import OAuthServerClient, OAuthServerLoginIntent
from belgie_oauth_server.metadata import (
    _ROOT_OAUTH_METADATA_PATH,
    _ROOT_OPENID_METADATA_PATH,
    build_oauth_metadata,
    build_oauth_metadata_well_known_path,
    build_openid_metadata,
    build_openid_metadata_well_known_path,
    build_protected_resource_metadata,
    build_protected_resource_metadata_well_known_path,
)
from belgie_oauth_server.models import (
    InvalidRedirectUriError,
    OAuthServerClientInformationFull,
    OAuthServerClientMetadata,
    OAuthServerConsentResponse,
    OAuthServerErrorResponse,
    OAuthServerIntrospectionResponse,
    OAuthServerMetadata,
    OAuthServerPublicClient,
    OAuthServerToken,
    OIDCMetadata,
    ProtectedResourceMetadata,
    UserInfoResponse,
)
from belgie_oauth_server.provider import AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.rate_limit import OAuthServerRateLimiter
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import (
    construct_redirect_uri,
    create_code_challenge,
    is_fetch_request,
    join_url,
)
from belgie_oauth_server.verifier import verify_local_access_token

_ROOT_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
ACCESS_TOKEN_HINT = "access_token"  # noqa: S105
REFRESH_TOKEN_HINT = "refresh_token"  # noqa: S105
BEARER_TOKEN_TYPE = "Bearer"  # noqa: S105
REFRESH_TOKEN_TYPE = "refresh_token"  # noqa: S105
type JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
type FormValue = str | UploadFile
type FormInput = Mapping[str, FormValue] | FormData
type AuthorizePrompt = Literal["none", "consent", "login", "create", "select_account"]


@dataclass(frozen=True, slots=True, kw_only=True)
class _TokenHandlerContext:
    client: BelgieClient
    form: FormInput
    provider: SimpleOAuthProvider
    settings: OAuthServer
    belgie_base_url: str
    issuer_url: str
    client_id: str | None
    client_secret: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _AuthorizeRequestContext:
    oauth_client: OAuthServerClientInformationFull
    params: AuthorizationParams
    prompt_values: frozenset[AuthorizePrompt]
    redirect_uri: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _InteractionError:
    error: str
    description: str


class _SessionLike(Protocol):
    id: UUID
    created_at: datetime


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
        self._metadata_router: APIRouter | None = None
        self._resolve_client: Callable[..., OAuthServerClient] | None = None
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

        def resolve_client(_client: BelgieClientDep) -> OAuthServerClient:
            return OAuthServerClient(provider=provider, issuer_url=issuer_url)

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    def __call__(self, *args: object, **kwargs: object) -> OAuthServerClient:
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
        self._ensure_dependency_resolver(belgie, provider, issuer_url)

        self._metadata_router = self.metadata_router(belgie)

        router = APIRouter(prefix=self._settings.prefix, tags=["oauth"])
        metadata = build_oauth_metadata(issuer_url, self._settings)
        openid_metadata = build_openid_metadata(issuer_url, self._settings)

        router = self._add_metadata_route(router, metadata)
        router = self._add_openid_metadata_route(router, openid_metadata)
        router = self._add_jwks_route(router, provider)
        router = self._add_authorize_route(router, belgie, provider, self._settings, issuer_url, self._rate_limiter)
        router = self._add_token_route(
            router,
            belgie,
            provider,
            self._settings,
            belgie.settings.base_url,
            issuer_url,
            self._rate_limiter,
        )
        router = self._add_register_route(router, belgie, provider, self._settings, self._rate_limiter)
        router = self._add_revoke_route(router, provider, self._settings, self._rate_limiter)
        router = self._add_userinfo_route(router, belgie, provider, self._settings, self._rate_limiter)
        router = self._add_end_session_route(router, belgie, provider, issuer_url)
        router = self._add_login_route(router, belgie, issuer_url, self._settings, provider)
        router = self._add_continue_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_consent_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_login_callback_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_client_management_routes(router, belgie, provider, self._settings)
        router = self._add_consent_management_routes(router, belgie, provider, self._settings)
        return self._add_introspect_route(router, belgie, provider, self._settings, self._rate_limiter)

    def metadata_router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )
        metadata = build_oauth_metadata(issuer_url, self._settings)
        well_known_path = build_oauth_metadata_well_known_path(issuer_url)

        openid_metadata = build_openid_metadata(issuer_url, self._settings)
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
        )
        router.add_api_route(
            openid_well_known_path,
            openid_metadata_handler,
            methods=["GET"],
            response_model=OIDCMetadata,
        )

        if self._settings.include_root_oauth_metadata_fallback and well_known_path != _ROOT_OAUTH_METADATA_PATH:
            router.add_api_route(
                _ROOT_OAUTH_METADATA_PATH,
                metadata_handler,
                methods=["GET"],
                response_model=OAuthServerMetadata,
            )

        if (
            self._settings.include_root_openid_metadata_fallback
            and openid_well_known_path != _ROOT_OPENID_METADATA_PATH
        ):
            router.add_api_route(
                _ROOT_OPENID_METADATA_PATH,
                openid_metadata_handler,
                methods=["GET"],
                response_model=OIDCMetadata,
            )

        resolved_resource = self._settings.resolve_resource(belgie.settings.base_url)
        if resolved_resource is not None:
            resource_url, resource_scopes = resolved_resource
            protected_resource_metadata = build_protected_resource_metadata(
                issuer_url,
                resource_url=resource_url,
                resource_scopes=resource_scopes,
                settings=self._settings,
            )
            protected_resource_well_known_path = build_protected_resource_metadata_well_known_path(
                resource_url,
            )

            async def protected_resource_metadata_handler(_: Request) -> "ProtectedResourceMetadata":
                return protected_resource_metadata

            router.add_api_route(
                protected_resource_well_known_path,
                protected_resource_metadata_handler,
                methods=["GET"],
                response_model=ProtectedResourceMetadata,
            )

            if (
                self._settings.include_root_resource_metadata_fallback
                and protected_resource_well_known_path != _ROOT_RESOURCE_METADATA_PATH
            ):
                router.add_api_route(
                    _ROOT_RESOURCE_METADATA_PATH,
                    protected_resource_metadata_handler,
                    methods=["GET"],
                    response_model=ProtectedResourceMetadata,
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
        )
        return router

    @staticmethod
    def _add_jwks_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:
        async def jwks_handler(_: Request) -> dict[str, list[dict[str, JSONValue]]]:
            if provider.signing_state.jwks is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="jwks unavailable")
            return provider.signing_state.jwks

        router.add_api_route("/jwks", jwks_handler, methods=["GET"])
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

        async def _authorize(  # noqa: C901, PLR0911
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
                    login_url = _build_login_redirect(issuer_url, state_value)
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
                state_value = await _authorize_state(
                    provider,
                    authorize_request.oauth_client,
                    replace(params_with_principal, intent=interaction),
                )
                login_url = _build_login_redirect(issuer_url, state_value)
                return _redirect_response(request, login_url)

            if settings.consent_url is None:
                reference_id = await _resolve_consent_reference(
                    settings,
                    authorize_request.oauth_client,
                    params_with_principal,
                )
                await provider.save_consent(
                    authorize_request.oauth_client.client_id or settings.client_id,
                    str(individual.id),
                    params_with_principal.scopes or [settings.default_scope],
                    reference_id=reference_id,
                )
            state_value = await _authorize_state(provider, authorize_request.oauth_client, params_with_principal)
            redirect_url = await _issue_authorization_code(provider, state_value, issuer_url)
            return _redirect_response(request, redirect_url)

        async def authorize_get_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            return await _authorize(request, client)

        async def authorize_post_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> Response:
            return await _authorize(request, client)

        router.add_api_route("/authorize", authorize_get_handler, methods=["GET"])
        router.add_api_route("/authorize", authorize_post_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_token_route(  # noqa: PLR0913
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        belgie_base_url: str,
        issuer_url: str,
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
            client_id, client_secret, auth_error = _extract_client_credentials(request, form)
            if auth_error is not None:
                return auth_error

            token_context = _TokenHandlerContext(
                client=client,
                form=form,
                provider=provider,
                settings=settings,
                belgie_base_url=belgie_base_url,
                issuer_url=issuer_url,
                client_id=client_id,
                client_secret=client_secret,
            )

            if grant_type == "authorization_code":
                return await _handle_authorization_code_grant(token_context)

            if grant_type == "refresh_token":
                return await _handle_refresh_token_grant(token_context)

            if grant_type == "client_credentials":
                return await _handle_client_credentials_grant(token_context)

            return _oauth_error("unsupported_grant_type", status_code=status.HTTP_400_BAD_REQUEST)

        router.add_api_route("/token", token_handler, methods=["POST"], response_model=OAuthServerToken)
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
        ) -> OAuthServerClientInformationFull | Response:
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
                metadata = OAuthServerClientMetadata.model_validate(payload)
            except ValidationError as exc:
                return _oauth_error(
                    "invalid_request",
                    _format_validation_error(exc),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            except ValueError as exc:
                description = str(exc) or "invalid client metadata"
                return _oauth_error("invalid_request", description, status_code=status.HTTP_400_BAD_REQUEST)

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
                    return _oauth_error(
                        "invalid_request",
                        "client_credentials is not allowed for unauthenticated client registration",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                if metadata.require_pkce is False:
                    return _oauth_error(
                        "invalid_request",
                        "pkce is required for registered clients",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                if metadata.skip_consent:
                    return _oauth_error(
                        "invalid_request",
                        "skip_consent cannot be set during dynamic client registration",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                metadata = metadata.model_copy(
                    update={
                        "token_endpoint_auth_method": "none",
                        "type": None if metadata.type == "web" else metadata.type,
                    },
                )

            try:
                provider.validate_client_metadata(metadata)
                client_info = await provider.register_client(
                    metadata,
                    individual_id=authenticated_individual_id,
                    db=client.db,
                )
            except ValueError as exc:
                description = str(exc) or "invalid client metadata"
                return _oauth_error("invalid_request", description, status_code=status.HTTP_400_BAD_REQUEST)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            return client_info

        router.add_api_route(
            "/register",
            register_handler,
            methods=["POST"],
            response_model=OAuthServerClientInformationFull,
            response_model_exclude_none=True,
            status_code=status.HTTP_201_CREATED,
        )
        return router

    @staticmethod
    def _add_revoke_route(  # noqa: C901
        router: APIRouter,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        async def revoke_handler(request: Request) -> Response:  # noqa: C901, PLR0911
            if (
                rate_limited := _enforce_rate_limit(
                    request,
                    rate_limiter,
                    "revoke",
                    settings.rate_limit.revoke,
                )
            ) is not None:
                return rate_limited
            form = await request.form()
            client_id, client_secret, auth_error = _extract_client_credentials(request, form)
            if auth_error is not None:
                return auth_error

            oauth_client, error = await _authenticate_client(
                provider,
                client_id,
                client_secret,
                require_credentials=True,
                require_confidential=True,
            )
            if error is not None:
                return error
            if oauth_client is None:
                return _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)

            token: str | None = _get_str(form, "token")
            if not token:
                return _oauth_error("invalid_request", "missing token", status_code=status.HTTP_400_BAD_REQUEST)
            if token.startswith("Bearer "):
                token = token.removeprefix("Bearer ")

            token_type_hint, hint_error = _parse_token_type_hint(form)
            if hint_error is not None:
                return hint_error

            if token_type_hint in {None, ACCESS_TOKEN_HINT}:
                access_token = await provider.load_access_token(token)
                if access_token is not None and access_token.client_id == oauth_client.client_id:
                    await provider.revoke_token(access_token)
                if token_type_hint == ACCESS_TOKEN_HINT:
                    return JSONResponse({})

            if token_type_hint in {None, REFRESH_TOKEN_HINT}:
                refresh_token = await provider.load_refresh_token(token)
                if refresh_token is not None and refresh_token.client_id == oauth_client.client_id:
                    await provider.revoke_token(refresh_token)
            return JSONResponse({})

        router.add_api_route("/revoke", revoke_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_userinfo_route(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
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

            verified_access_token = await verify_local_access_token(provider, token_value)
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
            return UserInfoResponse.model_validate(
                {
                    **_build_user_claims(
                        user,
                        access_token.scopes,
                        subject_identifier=subject_identifier,
                    ),
                    **(
                        await _resolve_custom_mapping(
                            settings.custom_userinfo_claims,
                            {
                                "client_id": oauth_client.client_id,
                                "scopes": list(access_token.scopes),
                                "subject_identifier": subject_identifier,
                                "user_id": str(user.id),
                                "metadata_json": oauth_client.metadata_json or {},
                            },
                        )
                    ),
                },
            )

        router.add_api_route(
            "/userinfo",
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
                payload = jwt.decode(
                    id_token_hint,
                    provider.signing_state.verification_key,
                    algorithms=[provider.signing_state.algorithm],
                    audience=inferred_client_id,
                    issuer=issuer_url,
                    options={"require": ["iss", "aud", "exp", "iat", "sub"]},
                )
            except InvalidTokenError:
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

        router.add_api_route("/end-session", end_session_handler, methods=["GET"])
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

        router.add_api_route("/login", login_handler, methods=["GET"])
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
            state = _get_payload_str(payload, "state")
            if not state:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state")

            created = _get_payload_bool(payload, "created")
            selected = _get_payload_bool(payload, "selected")
            post_login = _get_payload_bool(payload, "post_login")
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
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            return _redirect_response(request, redirect_url)

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

        router.add_api_route("/continue", continue_get_handler, methods=["GET"])
        router.add_api_route("/continue", continue_post_handler, methods=["POST"])
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
            state = _get_payload_str(payload, "state")
            if not state:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state")

            state_data = await provider.load_authorization_state(state)
            if state_data is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter")

            accepted = _get_payload_bool(payload, "accept")
            if accepted is not True:
                redirect_url = _authorize_error_redirect_url(
                    state_data.redirect_uri,
                    error="access_denied",
                    description="User denied access",
                    state=state,
                    issuer_url=issuer_url,
                )
                return _redirect_response(request, redirect_url)

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

            requested_scopes = _parse_scope_param(_get_payload_str(payload, "scope"))
            original_scopes = state_data.scopes or [settings.default_scope]
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
                    oauth_client.client_id or settings.client_id,
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
            return _redirect_response(request, redirect_url)

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

        router.add_api_route("/consent", consent_get_handler, methods=["GET"])
        router.add_api_route("/consent", consent_post_handler, methods=["POST"])
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
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            return _redirect_response(request, redirect_url)

        router.add_api_route("/login/callback", login_callback_handler, methods=["GET"])
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
            client: BelgieClientDep,
        ) -> OAuthServerClientInformationFull | Response:
            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)
                raise

            try:
                payload = await request.json()
                metadata = OAuthServerClientMetadata.model_validate(payload)
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
                provider.validate_client_metadata(metadata)
                return await provider.register_client(
                    metadata,
                    individual_id=str(individual.id),
                    reference_id=reference_id,
                    db=client.db,
                )
            except ValueError as exc:
                return _oauth_error("invalid_request", str(exc), status_code=status.HTTP_400_BAD_REQUEST)

        async def list_clients_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> list[OAuthServerClientInformationFull] | Response:
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
                if oauth_client.client_id is not None:
                    deduped[oauth_client.client_id] = _redact_client_secret(oauth_client)
            return list(deduped.values())

        async def prelogin_client_handler(state: str) -> OAuthServerPublicClient | Response:
            if not settings.allow_public_client_prelogin:
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            state_data = await provider.load_authorization_state(state)
            if state_data is None:
                return _oauth_error(
                    "invalid_request",
                    "Invalid state parameter",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            oauth_client = await provider.get_client(state_data.client_id)
            if oauth_client is None or oauth_client.disabled:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            return _public_client_information(oauth_client)

        async def public_client_handler(client_id: str) -> OAuthServerPublicClient | Response:
            oauth_client = await provider.get_client(client_id)
            if oauth_client is None or oauth_client.disabled:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            return _public_client_information(oauth_client)

        async def get_client_handler(
            request: Request,
            client_id: str,
            client: BelgieClientDep,
        ) -> OAuthServerClientInformationFull | Response:
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
            return _redact_client_secret(oauth_client)

        async def update_client_handler(
            request: Request,
            client_id: str,
            client: BelgieClientDep,
        ) -> OAuthServerClientInformationFull | Response:
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

            raw_payload = await request.json()
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
            updates = _normalize_client_updates(payload)
            if "reference_id" in updates:
                new_reference_id = updates["reference_id"]
                resolved_reference = await _resolve_client_reference_id(settings, individual_id, session_id)
                if (
                    isinstance(new_reference_id, str)
                    and new_reference_id != resolved_reference
                    and not await _has_client_privilege(settings, "update", individual_id, session_id, new_reference_id)
                ):
                    return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)

            updated_client = await provider.update_client(client_id, updates=updates, db=client.db)
            if updated_client is None:
                return _oauth_error("not_found", "client not found", status_code=status.HTTP_404_NOT_FOUND)
            return _redact_client_secret(updated_client)

        async def delete_client_handler(
            request: Request,
            client_id: str,
            client: BelgieClientDep,
        ) -> Response:
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

            await provider.delete_client(client_id, db=client.db)
            return JSONResponse({})

        async def rotate_client_secret_handler(
            request: Request,
            client_id: str,
            client: BelgieClientDep,
        ) -> OAuthServerClientInformationFull | Response:
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
            return rotated_client

        router.add_api_route(
            "/clients/prelogin",
            prelogin_client_handler,
            methods=["GET"],
            response_model=OAuthServerPublicClient,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            "/clients/{client_id}/public",
            public_client_handler,
            methods=["GET"],
            response_model=OAuthServerPublicClient,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            "/clients",
            create_client_handler,
            methods=["POST"],
            response_model=OAuthServerClientInformationFull,
            response_model_exclude_none=True,
            status_code=status.HTTP_201_CREATED,
        )
        router.add_api_route(
            "/clients",
            list_clients_handler,
            methods=["GET"],
            response_model=list[OAuthServerClientInformationFull],
            response_model_exclude_none=True,
        )
        router.add_api_route(
            "/clients/{client_id}",
            get_client_handler,
            methods=["GET"],
            response_model=OAuthServerClientInformationFull,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            "/clients/{client_id}",
            update_client_handler,
            methods=["PATCH"],
            response_model=OAuthServerClientInformationFull,
            response_model_exclude_none=True,
        )
        router.add_api_route("/clients/{client_id}", delete_client_handler, methods=["DELETE"])
        router.add_api_route(
            "/clients/{client_id}/rotate-secret",
            rotate_client_secret_handler,
            methods=["POST"],
            response_model=OAuthServerClientInformationFull,
            response_model_exclude_none=True,
        )
        return router

    @staticmethod
    def _add_consent_management_routes(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
    ) -> APIRouter:
        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        async def list_consents_handler(
            request: Request,
            client: BelgieClientDep,
        ) -> list[OAuthServerConsentResponse] | Response:
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
            consent_id: UUID,
            client: BelgieClientDep,
        ) -> OAuthServerConsentResponse | Response:
            consent = await provider.get_consent_by_id(consent_id, db=client.db)
            if consent is None:
                return _oauth_error("not_found", "consent not found", status_code=status.HTTP_404_NOT_FOUND)
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_consent(
                settings,
                consent,
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            return _serialize_consent(consent)

        async def update_consent_handler(
            request: Request,
            consent_id: UUID,
            client: BelgieClientDep,
        ) -> OAuthServerConsentResponse | Response:
            existing_consent = await provider.get_consent_by_id(consent_id, db=client.db)
            if existing_consent is None:
                return _oauth_error("not_found", "consent not found", status_code=status.HTTP_404_NOT_FOUND)
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_consent(
                settings,
                existing_consent,
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            payload = await request.json()
            scopes = payload.get("scopes") if isinstance(payload, dict) else None
            if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
                return _oauth_error(
                    "invalid_request",
                    "scopes must be provided",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            updated_consent = await provider.update_consent(consent_id, scopes=list(scopes), db=client.db)
            if updated_consent is None:
                return _oauth_error("not_found", "consent not found", status_code=status.HTTP_404_NOT_FOUND)
            return _serialize_consent(updated_consent)

        async def delete_consent_handler(
            request: Request,
            consent_id: UUID,
            client: BelgieClientDep,
        ) -> Response:
            existing_consent = await provider.get_consent_by_id(consent_id, db=client.db)
            if existing_consent is None:
                return _oauth_error("not_found", "consent not found", status_code=status.HTTP_404_NOT_FOUND)
            individual = await client.get_individual(SecurityScopes(), request)
            session = await client.get_session(request)
            if not await _can_manage_consent(
                settings,
                existing_consent,
                individual_id=str(individual.id),
                session_id=str(session.id),
            ):
                return _oauth_error("access_denied", status_code=status.HTTP_403_FORBIDDEN)
            await provider.delete_consent(consent_id, db=client.db)
            return JSONResponse({})

        router.add_api_route(
            "/consents",
            list_consents_handler,
            methods=["GET"],
            response_model=list[OAuthServerConsentResponse],
            response_model_exclude_none=True,
        )
        router.add_api_route(
            "/consents/{consent_id}",
            get_consent_handler,
            methods=["GET"],
            response_model=OAuthServerConsentResponse,
            response_model_exclude_none=True,
        )
        router.add_api_route(
            "/consents/{consent_id}",
            update_consent_handler,
            methods=["PATCH"],
            response_model=OAuthServerConsentResponse,
            response_model_exclude_none=True,
        )
        router.add_api_route("/consents/{consent_id}", delete_consent_handler, methods=["DELETE"])
        return router

    @staticmethod
    def _add_introspect_route(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        rate_limiter: OAuthServerRateLimiter,
    ) -> APIRouter:
        async def introspect_handler(  # noqa: C901, PLR0911, PLR0912
            request: Request,
            response: Response,
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
            form = await request.form()
            client_id, client_secret, auth_error = _extract_client_credentials(request, form)
            if auth_error is not None:
                return auth_error

            oauth_client, error = await _authenticate_client(
                provider,
                client_id,
                client_secret,
                require_credentials=True,
                require_confidential=True,
            )
            if error is not None:
                return error
            if oauth_client is None:
                return _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)

            token = _get_str(form, "token")
            if not token:
                response.status_code = status.HTTP_400_BAD_REQUEST
                return OAuthServerIntrospectionResponse(active=False)
            if token.startswith("Bearer "):
                token = token.removeprefix("Bearer ")

            token_type_hint, hint_error = _parse_token_type_hint(form)
            if hint_error is not None:
                return hint_error

            if token_type_hint in {None, ACCESS_TOKEN_HINT}:
                verified_access_token = await verify_local_access_token(provider, token)
                if (
                    verified_access_token is not None
                    and verified_access_token.token.client_id == oauth_client.client_id
                ):
                    access_token = verified_access_token.token
                    access_token_client = await provider.get_client(access_token.client_id)
                    if access_token_client is None or access_token_client.disabled:
                        return OAuthServerIntrospectionResponse(active=False)
                    active_session_id = await _resolve_active_session_id(client, access_token.session_id)
                    subject_identifier = (
                        provider.resolve_subject_identifier(access_token_client, access_token.individual_id)
                        if access_token_client is not None and access_token.individual_id is not None
                        else access_token.individual_id
                    )
                    return OAuthServerIntrospectionResponse(
                        active=True,
                        client_id=access_token.client_id,
                        scope=" ".join(access_token.scopes),
                        exp=access_token.expires_at,
                        iat=access_token.created_at,
                        token_type=BEARER_TOKEN_TYPE,
                        aud=access_token.resource,
                        sub=subject_identifier,
                        sid=active_session_id,
                        iss=provider.issuer_url,
                    )
                if token_type_hint == ACCESS_TOKEN_HINT:
                    return OAuthServerIntrospectionResponse(active=False)

            if token_type_hint in {None, REFRESH_TOKEN_HINT}:
                refresh_token = await provider.load_refresh_token(token)
                if refresh_token and refresh_token.client_id == oauth_client.client_id:
                    refresh_token_client = await provider.get_client(refresh_token.client_id)
                    if refresh_token_client is None or refresh_token_client.disabled:
                        return OAuthServerIntrospectionResponse(active=False)
                    active_session_id = await _resolve_active_session_id(client, refresh_token.session_id)
                    subject_identifier = (
                        provider.resolve_subject_identifier(refresh_token_client, refresh_token.individual_id)
                        if refresh_token_client is not None and refresh_token.individual_id is not None
                        else refresh_token.individual_id
                    )
                    return OAuthServerIntrospectionResponse(
                        active=True,
                        client_id=refresh_token.client_id,
                        scope=" ".join(refresh_token.scopes),
                        exp=refresh_token.expires_at,
                        iat=refresh_token.created_at,
                        token_type=REFRESH_TOKEN_TYPE,
                        aud=refresh_token.resource,
                        sub=subject_identifier,
                        sid=active_session_id,
                        iss=provider.issuer_url,
                    )

            return OAuthServerIntrospectionResponse(active=False)

        router.add_api_route(
            "/introspect",
            introspect_handler,
            methods=["POST"],
            response_model=OAuthServerIntrospectionResponse,
            response_model_exclude_none=True,
        )
        return router


def _build_issuer_url(belgie: Belgie, settings: OAuthServer) -> str:
    parsed = urlparse(belgie.settings.base_url)
    base_path = parsed.path.rstrip("/")
    prefix = settings.prefix.strip("/")
    auth_path = "auth"
    full_path = f"{base_path}/{auth_path}/{prefix}" if prefix else f"{base_path}/{auth_path}"
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))


async def _parse_authorize_request(  # noqa: C901, PLR0911, PLR0912
    data: dict[str, str],
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    belgie_base_url: str,
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
        validated_redirect_uri = oauth_client.validate_redirect_uri(redirect_uri)
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
    requested_scopes = _parse_scope_param(scope_raw)
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
    code_challenge_method = _get_str(resolved_data, "code_challenge_method")
    pkce_error = _validate_pkce_inputs(oauth_client, scopes, code_challenge, code_challenge_method)
    if pkce_error is not None:
        return _authorize_error(
            "invalid_request",
            pkce_error,
            redirect_uri=redirect_uri_string,
            state=_get_str(resolved_data, "state"),
            issuer_url=issuer_url,
        )

    try:
        resource = _validate_authorize_resource(settings, belgie_base_url, _get_str(resolved_data, "resource"))
    except HTTPException:
        return _authorize_error(
            "invalid_target",
            redirect_uri=redirect_uri_string,
            state=_get_str(resolved_data, "state"),
            issuer_url=issuer_url,
        )

    state = _get_str(resolved_data, "state") or secrets.token_hex(16)
    prompt = _normalize_prompt_values(prompt_values)

    params = AuthorizationParams(
        state=state,
        scopes=scopes,
        code_challenge=code_challenge,
        redirect_uri=validated_redirect_uri,
        redirect_uri_provided_explicitly=redirect_uri_raw is not None,
        resource=resource,
        nonce=_get_str(resolved_data, "nonce"),
        prompt=prompt,
        intent=_derive_initial_intent(prompt_values),
    )
    return _AuthorizeRequestContext(
        oauth_client=oauth_client,
        params=params,
        prompt_values=prompt_values,
        redirect_uri=redirect_uri_string,
    )


def _normalize_resource_path(path: str) -> str:
    if path in {"", "/"}:
        return "/"
    if path.endswith("/"):
        return path.removesuffix("/")
    return path


def _resource_urls_match(left_resource: str, right_resource: str) -> bool:
    left = urlparse(left_resource)
    right = urlparse(right_resource)
    return (
        left.scheme == right.scheme
        and left.netloc == right.netloc
        and _normalize_resource_path(left.path) == _normalize_resource_path(right.path)
        and left.params == right.params
        and left.query == right.query
        and left.fragment == right.fragment
    )


def _validate_authorize_resource(
    settings: OAuthServer,
    belgie_base_url: str,
    resource: str | None,
) -> str | None:
    if resource is None:
        return None

    configured_resource = settings.resolve_resource(belgie_base_url)
    if configured_resource is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_target")

    resource_url, _resource_scopes = configured_resource
    configured_resource_url = str(resource_url)
    if not _resource_urls_match(configured_resource_url, resource):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_target")
    return configured_resource_url


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


def _build_login_redirect(issuer_url: str, state: str) -> str:
    return construct_redirect_uri(join_url(issuer_url, "login"), state=state)


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


def _pkce_requirement_for_client(
    oauth_client: OAuthServerClientInformationFull,
    scopes: list[str],
) -> str | None:
    is_public_client = oauth_client.token_endpoint_auth_method == "none" or oauth_client.type in {  # noqa: S105
        "native",
        "user-agent-based",
    }
    if is_public_client:
        return "pkce is required for public clients"
    if "offline_access" in scopes:
        return "pkce is required when requesting offline_access scope"
    if oauth_client.require_pkce is not False:
        return "pkce is required for this client"
    return None


def _validate_pkce_inputs(
    oauth_client: OAuthServerClientInformationFull,
    scopes: list[str],
    code_challenge: str | None,
    code_challenge_method: str | None,
) -> str | None:
    pkce_requirement = _pkce_requirement_for_client(oauth_client, scopes)
    if pkce_requirement is not None and not code_challenge:
        return pkce_requirement
    if code_challenge or code_challenge_method:
        if not code_challenge or not code_challenge_method:
            return "code_challenge and code_challenge_method must both be provided"
        if code_challenge_method != "S256":
            return "invalid code_challenge method, only S256 is supported"
    return None


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
    if settings.consent_url is not None and await _consent_required(provider, settings, oauth_client, params):
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
    if oauth_client.skip_consent:
        return False
    reference_id = await _resolve_consent_reference(settings, oauth_client, params)
    return not await provider.has_consent(
        oauth_client.client_id or settings.client_id,
        params.individual_id,
        params.scopes or [settings.default_scope],
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
        oauth_client.client_id or settings.client_id,
        params.individual_id,
        params.session_id,
        params.scopes or [settings.default_scope],
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
        oauth_client.client_id or settings.client_id,
        params.individual_id,
        params.session_id,
        params.scopes or [settings.default_scope],
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
        oauth_client.client_id or settings.client_id,
        params.individual_id,
        params.session_id,
        params.scopes or [settings.default_scope],
    )
    if inspect.isawaitable(resolved_reference):
        resolved_reference = await resolved_reference
    return resolved_reference


async def _resume_authorization_flow(
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    state: str,
    *,
    handled_prompt: AuthorizePrompt | Literal["post_login"],
    issuer_url: str,
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
        return _build_login_redirect(issuer_url, state)

    if state_data.individual_id is not None and settings.consent_url is None:
        reference_id = await _resolve_consent_reference(settings, oauth_client, params)
        await provider.save_consent(
            oauth_client.client_id or settings.client_id,
            state_data.individual_id,
            state_data.scopes or [settings.default_scope],
            reference_id=reference_id,
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
        return construct_redirect_uri(join_url(issuer_url, "continue"), state=state, created="true")
    if intent == "select_account":
        return construct_redirect_uri(join_url(issuer_url, "continue"), state=state, selected="true")
    if intent == "post_login":
        return construct_redirect_uri(join_url(issuer_url, "continue"), state=state, post_login="true")
    if intent == "consent":
        return construct_redirect_uri(join_url(issuer_url, "consent"), state=state)
    return construct_redirect_uri(join_url(issuer_url, "login/callback"), state=state)


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
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
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
        return JSONResponse({"redirect_to": url, "redirect_url": url})
    return RedirectResponse(url=url, status_code=status_code)


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


def _extract_client_credentials(
    request: Request,
    form: FormInput,
) -> tuple[str | None, str | None, JSONResponse | None]:
    client_id = _get_str(form, "client_id")
    client_secret = _get_str(form, "client_secret")
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Basic "):
        try:
            basic_client_id, basic_client_secret = _parse_basic_authorization(authorization)
        except ValueError:
            return None, None, _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)
        client_id = basic_client_id
        client_secret = basic_client_secret
    return client_id, client_secret, None


def _parse_basic_authorization(value: str) -> tuple[str, str]:
    encoded = value.removeprefix("Basic ").strip()
    if not encoded:
        msg = "invalid basic auth"
        raise ValueError(msg)
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        msg = "invalid basic auth"
        raise ValueError(msg) from exc

    if ":" not in decoded:
        msg = "invalid basic auth"
        raise ValueError(msg)
    client_id, client_secret = decoded.split(":", 1)
    if not client_id:
        msg = "invalid basic auth"
        raise ValueError(msg)
    return client_id, client_secret


async def _authenticate_client(
    provider: SimpleOAuthProvider,
    client_id: str | None,
    client_secret: str | None,
    *,
    require_credentials: bool = False,
    require_confidential: bool = False,
) -> tuple[OAuthServerClientInformationFull | None, JSONResponse | None]:
    if not client_id:
        return None, _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)

    oauth_client = await provider.authenticate_client(
        client_id,
        client_secret,
        require_credentials=require_credentials,
        require_confidential=require_confidential,
    )
    if not oauth_client:
        return None, _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)
    return oauth_client, None


async def _handle_authorization_code_grant(  # noqa: C901, PLR0911, PLR0912
    ctx: _TokenHandlerContext,
) -> OAuthServerToken | Response:
    oauth_client, error = await _authenticate_client(
        ctx.provider,
        ctx.client_id,
        ctx.client_secret,
    )
    if error is not None:
        return error
    if oauth_client is None:
        return _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)

    code = _get_str(ctx.form, "code")
    if not code:
        return _oauth_error("invalid_request", "missing code", status_code=status.HTTP_400_BAD_REQUEST)

    authorization_code = await ctx.provider.load_authorization_code(code)
    if not authorization_code:
        return _oauth_error("invalid_grant", status_code=status.HTTP_400_BAD_REQUEST)

    if authorization_code.expires_at < time.time():
        return _oauth_error("invalid_grant", "code expired", status_code=status.HTTP_400_BAD_REQUEST)

    if oauth_client.client_id != authorization_code.client_id:
        return _oauth_error("invalid_grant", "client_id mismatch", status_code=status.HTTP_400_BAD_REQUEST)

    redirect_uri_raw = _get_str(ctx.form, "redirect_uri")
    if authorization_code.redirect_uri_provided_explicitly and not redirect_uri_raw:
        return _oauth_error("invalid_request", "missing redirect_uri", status_code=status.HTTP_400_BAD_REQUEST)
    if redirect_uri_raw and redirect_uri_raw != str(authorization_code.redirect_uri):
        return _oauth_error("invalid_grant", "redirect_uri mismatch", status_code=status.HTTP_400_BAD_REQUEST)

    code_verifier = _get_str(ctx.form, "code_verifier")
    pkce_required = _pkce_requirement_for_client(oauth_client, authorization_code.scopes)
    if authorization_code.code_challenge is not None and not code_verifier:
        return _oauth_error(
            "invalid_request",
            "code_verifier required because PKCE was used in authorization",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if authorization_code.code_challenge is None and code_verifier:
        return _oauth_error(
            "invalid_request",
            "code_verifier provided but PKCE was not used in authorization",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if authorization_code.code_challenge is None and pkce_required is not None:
        return _oauth_error("invalid_request", pkce_required, status_code=status.HTTP_400_BAD_REQUEST)
    if authorization_code.code_challenge is not None and code_verifier is not None:
        expected_challenge = create_code_challenge(code_verifier)
        if expected_challenge != authorization_code.code_challenge:
            return _oauth_error("invalid_grant", "invalid code_verifier", status_code=status.HTTP_400_BAD_REQUEST)

    requested_resource = _get_str(ctx.form, "resource")
    resolved_resource, resource_error = _resolve_token_resource(
        ctx.settings,
        ctx.belgie_base_url,
        requested_resource=requested_resource,
        bound_resource=authorization_code.resource,
        require_bound_match=True,
    )
    if resource_error is not None:
        return resource_error

    token = await ctx.provider.exchange_authorization_code(
        authorization_code,
        issue_refresh_token="offline_access" in authorization_code.scopes,
        access_token_resource=_build_access_token_audience(
            ctx.issuer_url,
            base_resource=resolved_resource,
            scopes=authorization_code.scopes,
        ),
    )
    return await _apply_custom_token_response_fields(
        ctx.settings,
        {
            **token.model_dump(),
            "id_token": await _maybe_build_id_token(
                ctx.client,
                ctx.provider,
                ctx.settings,
                ctx.issuer_url,
                oauth_client,
                scopes=authorization_code.scopes,
                individual_id=authorization_code.individual_id,
                nonce=authorization_code.nonce,
                session_id=authorization_code.session_id,
            ),
        },
        grant_type="authorization_code",
        oauth_client=oauth_client,
        scopes=authorization_code.scopes,
    )


async def _handle_refresh_token_grant(ctx: _TokenHandlerContext) -> OAuthServerToken | Response:  # noqa: C901, PLR0911
    oauth_client, error = await _authenticate_client(
        ctx.provider,
        ctx.client_id,
        ctx.client_secret,
    )
    if error is not None:
        return error
    if oauth_client is None:
        return _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)

    refresh_token_value = _get_str(ctx.form, "refresh_token")
    if not refresh_token_value:
        return _oauth_error("invalid_request", "missing refresh_token", status_code=status.HTTP_400_BAD_REQUEST)

    refresh_token = await ctx.provider.load_refresh_token(refresh_token_value)
    if not refresh_token:
        refresh_token = await ctx.provider.load_refresh_token(refresh_token_value, include_revoked=True)
    if not refresh_token:
        return _oauth_error("invalid_grant", status_code=status.HTTP_400_BAD_REQUEST)

    if refresh_token.client_id != oauth_client.client_id:
        return _oauth_error("invalid_grant", "client_id mismatch", status_code=status.HTTP_400_BAD_REQUEST)

    requested_scopes = _parse_scope_param(_get_str(ctx.form, "scope"))
    if requested_scopes is not None and not requested_scopes:
        return _oauth_error("invalid_scope", "missing scope", status_code=status.HTTP_400_BAD_REQUEST)
    scopes = requested_scopes or refresh_token.scopes
    if requested_scopes is not None:
        invalid_scopes = [scope for scope in requested_scopes if scope not in refresh_token.scopes]
        if invalid_scopes:
            return _oauth_error(
                "invalid_scope",
                f"unable to issue scope {invalid_scopes[0]}",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    requested_resource = _get_str(ctx.form, "resource")
    resolved_resource, resource_error = _resolve_token_resource(
        ctx.settings,
        ctx.belgie_base_url,
        requested_resource=requested_resource,
        bound_resource=refresh_token.resource,
        require_bound_match=True,
    )
    if resource_error is not None:
        return resource_error

    try:
        ctx.provider.validate_scopes_for_client(oauth_client, scopes)
    except ValueError as exc:
        return _oauth_error("invalid_scope", str(exc), status_code=status.HTTP_400_BAD_REQUEST)

    try:
        token = await ctx.provider.exchange_refresh_token(
            refresh_token,
            scopes,
            access_token_resource=_build_access_token_audience(
                ctx.issuer_url,
                base_resource=resolved_resource,
                scopes=scopes,
            ),
            refresh_token_resource=resolved_resource,
        )
    except ValueError as exc:
        return _oauth_error("invalid_grant", str(exc), status_code=status.HTTP_400_BAD_REQUEST)

    return await _apply_custom_token_response_fields(
        ctx.settings,
        {
            **token.model_dump(),
            "id_token": await _maybe_build_id_token(
                ctx.client,
                ctx.provider,
                ctx.settings,
                ctx.issuer_url,
                oauth_client,
                scopes=scopes,
                individual_id=refresh_token.individual_id,
                session_id=refresh_token.session_id,
            ),
        },
        grant_type="refresh_token",
        oauth_client=oauth_client,
        scopes=scopes,
    )


async def _handle_client_credentials_grant(ctx: _TokenHandlerContext) -> OAuthServerToken | Response:  # noqa: PLR0911
    oauth_client, error = await _authenticate_client(
        ctx.provider,
        ctx.client_id,
        ctx.client_secret,
        require_confidential=True,
    )
    if error is not None:
        return error
    if oauth_client is None:
        return _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)
    if oauth_client.client_id is None:
        return _oauth_error("invalid_client", status_code=status.HTTP_401_UNAUTHORIZED)

    requested_scopes = _parse_scope_param(_get_str(ctx.form, "scope"))
    if requested_scopes is not None and not requested_scopes:
        return _oauth_error("invalid_scope", "missing scope", status_code=status.HTTP_400_BAD_REQUEST)
    scopes = requested_scopes or ctx.provider.default_scopes_for_client(
        oauth_client,
        grant_type="client_credentials",
    )
    try:
        ctx.provider.validate_scopes_for_client(oauth_client, scopes, grant_type="client_credentials")
    except ValueError as exc:
        return _oauth_error("invalid_scope", str(exc), status_code=status.HTTP_400_BAD_REQUEST)

    requested_resource = _get_str(ctx.form, "resource")
    resolved_resource, resource_error = _resolve_token_resource(
        ctx.settings,
        ctx.belgie_base_url,
        requested_resource=requested_resource,
    )
    if resource_error is not None:
        return resource_error

    token = await ctx.provider.issue_client_credentials_token(
        oauth_client.client_id,
        scopes,
        resource=_build_access_token_audience(
            ctx.issuer_url,
            base_resource=resolved_resource,
            scopes=scopes,
        ),
    )
    return await _apply_custom_token_response_fields(
        ctx.settings,
        token.model_dump(),
        grant_type="client_credentials",
        oauth_client=oauth_client,
        scopes=scopes,
    )


def _parse_scope_param(scope: str | None) -> list[str] | None:
    if scope is None:
        return None
    parts = [segment for segment in scope.split(" ") if segment]
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return deduped


def _parse_token_type_hint(form: FormInput) -> tuple[str | None, JSONResponse | None]:
    token_type_hint = _get_str(form, "token_type_hint")
    if token_type_hint is None:
        return None, None
    if token_type_hint not in {ACCESS_TOKEN_HINT, REFRESH_TOKEN_HINT}:
        return None, _oauth_error(
            "invalid_request",
            "unsupported token_type_hint",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return token_type_hint, None


class _UserClaimsSource(Protocol):
    id: UUID | str
    name: str | None
    image: str | None
    email: str
    email_verified_at: datetime | None


def _build_user_claims(
    user: _UserClaimsSource,
    scopes: list[str],
    *,
    subject_identifier: str | None = None,
) -> dict[str, str | bool]:
    name_parts = [value for value in (user.name or "").split(" ") if value]
    payload: dict[str, str | bool] = {"sub": subject_identifier or str(user.id)}

    if "profile" in scopes:
        if user.name is not None:
            payload["name"] = user.name
        if user.image is not None:
            payload["picture"] = user.image
        if len(name_parts) > 1:
            payload["given_name"] = " ".join(name_parts[:-1])
            payload["family_name"] = name_parts[-1]

    if "email" in scopes:
        payload["email"] = user.email
        payload["email_verified"] = user.email_verified_at is not None

    return payload


async def _resolve_custom_mapping(
    resolver: Callable[[dict[str, object]], dict[str, object] | Awaitable[dict[str, object]]] | None,
    payload: dict[str, object],
) -> dict[str, object]:
    if resolver is None:
        return {}
    resolved = resolver(payload)
    custom_payload = await resolved if inspect.isawaitable(resolved) else resolved
    return dict(custom_payload or {})


async def _apply_custom_token_response_fields(
    settings: OAuthServer,
    payload: dict[str, object],
    *,
    grant_type: str,
    oauth_client: OAuthServerClientInformationFull,
    scopes: list[str],
) -> OAuthServerToken:
    custom_fields = await _resolve_custom_mapping(
        settings.custom_token_response_fields,
        {
            "grant_type": grant_type,
            "client_id": oauth_client.client_id,
            "scopes": list(scopes),
            "metadata_json": oauth_client.metadata_json or {},
        },
    )
    return OAuthServerToken.model_validate({**payload, **custom_fields})


async def _resolve_session_auth_time(client: BelgieClient, session_id: str | None) -> int | None:
    session = await _load_session(client, session_id)
    if session is None:
        return None

    created_at = getattr(session, "created_at", None)
    if created_at is None:
        return None
    return int(created_at.timestamp())


async def _resolve_active_session_id(client: BelgieClient, session_id: str | None) -> str | None:
    if session_id is None:
        return None

    session = await _load_session(client, session_id)
    if session is None:
        return None
    return str(session.id)


async def _load_session(client: BelgieClient, session_id: str | None) -> _SessionLike | None:  # noqa: PLR0911
    if session_id is None:
        return None
    try:
        parsed_session_id = UUID(session_id)
    except ValueError:
        return None

    session_manager = getattr(client, "session_manager", None)
    if session_manager is not None:
        db = getattr(client, "db", None)
        return await session_manager.get_session(db, parsed_session_id)

    session = getattr(client, "session", None)
    if session is None:
        return None

    active_session_id = getattr(session, "id", None)
    if active_session_id is None:
        return None
    if active_session_id == parsed_session_id or str(active_session_id) == session_id:
        return cast("_SessionLike", session)
    return None


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


def _public_client_information(client_info: OAuthServerClientInformationFull) -> OAuthServerPublicClient:
    if client_info.client_id is None:
        msg = "client_id is required"
        raise OAuthError(msg)
    return OAuthServerPublicClient(
        client_id=client_info.client_id,
        client_name=client_info.client_name,
        client_uri=client_info.client_uri,
        logo_uri=client_info.logo_uri,
        contacts=client_info.contacts,
        tos_uri=client_info.tos_uri,
        policy_uri=client_info.policy_uri,
    )


def _serialize_consent(consent: _ConsentLike) -> OAuthServerConsentResponse:
    return OAuthServerConsentResponse.model_validate(
        {
            "id": consent.id,
            "client_id": consent.client_id,
            "individual_id": consent.individual_id,
            "reference_id": consent.reference_id,
            "scopes": list(consent.scopes),
            "created_at": consent.created_at,
        },
    )


async def _can_manage_consent(
    settings: OAuthServer,
    consent: _ConsentLike,
    *,
    individual_id: str,
    session_id: str,
) -> bool:
    reference_id = consent.reference_id
    if await _has_client_privilege(settings, "read", individual_id, session_id, reference_id):
        return True
    if consent.individual_id != individual_id:
        return False
    if reference_id is None:
        return True
    return reference_id == await _resolve_client_reference_id(settings, individual_id, session_id)


def _normalize_client_updates(payload: Mapping[str, JSONValue]) -> dict[str, object]:
    list_fields = {"redirect_uris", "post_logout_redirect_uris", "contacts", "grant_types", "response_types"}
    string_fields = {
        "token_endpoint_auth_method",
        "scope",
        "client_name",
        "client_uri",
        "logo_uri",
        "tos_uri",
        "policy_uri",
        "jwks_uri",
        "software_id",
        "software_version",
        "software_statement",
        "type",
        "subject_type",
        "reference_id",
    }
    bool_fields = {"disabled", "skip_consent", "require_pkce", "enable_end_session"}
    dict_fields = {"jwks", "metadata_json"}

    normalized: dict[str, object] = {}
    for key, value in payload.items():
        if key in list_fields and isinstance(value, list):
            normalized[key] = [str(item) for item in value if isinstance(item, str)]
        elif (
            (key in string_fields and (value is None or isinstance(value, str)))
            or (key in bool_fields and (value is None or isinstance(value, bool)))
            or (key in dict_fields and (value is None or isinstance(value, dict)))
        ):
            normalized[key] = value
    return normalized


async def _maybe_build_id_token(  # noqa: PLR0913
    client: BelgieClient,
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    issuer_url: str,
    oauth_client: OAuthServerClientInformationFull,
    *,
    scopes: list[str],
    individual_id: str | None,
    nonce: str | None = None,
    session_id: str | None = None,
) -> str | None:
    if "openid" not in scopes:
        return None
    if individual_id is None:
        return None

    try:
        parsed_individual_id = UUID(individual_id)
    except ValueError:
        return None

    individual = await client.adapter.get_individual_by_id(client.db, parsed_individual_id)
    if individual is None:
        return None

    auth_time = await _resolve_session_auth_time(client, session_id)

    return await _build_id_token(
        provider,
        settings,
        issuer_url,
        oauth_client,
        user=individual,
        scopes=scopes,
        nonce=nonce,
        session_id=session_id,
        auth_time=auth_time,
    )


async def _build_id_token(  # noqa: PLR0913
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    issuer_url: str,
    oauth_client: OAuthServerClientInformationFull,
    *,
    user: _UserClaimsSource,
    scopes: list[str],
    nonce: str | None,
    session_id: str | None,
    auth_time: int | None = None,
) -> str:
    now = int(time.time())
    if oauth_client.client_id is None:
        msg = "registered client is missing client_id"
        raise OAuthError(msg)
    subject_identifier = provider.resolve_subject_identifier(oauth_client, str(user.id))
    payload: dict[str, str | int | bool] = {
        **_build_user_claims(user, scopes, subject_identifier=subject_identifier),
        "iss": issuer_url,
        "sub": subject_identifier,
        "aud": oauth_client.client_id,
        "iat": now,
        "exp": now + settings.id_token_ttl_seconds,
        "acr": "urn:mace:incommon:iap:bronze",
    }
    if nonce:
        payload["nonce"] = nonce
    if auth_time is not None:
        payload["auth_time"] = auth_time
    if oauth_client.enable_end_session and session_id:
        payload["sid"] = session_id

    payload.update(
        await _resolve_custom_mapping(
            settings.custom_id_token_claims,
            {
                "client_id": oauth_client.client_id,
                "scopes": list(scopes),
                "subject_identifier": subject_identifier,
                "user_id": str(user.id),
                "metadata_json": oauth_client.metadata_json or {},
            },
        ),
    )
    return provider.signing_state.sign(payload)


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


def _resolve_token_resource(
    settings: OAuthServer,
    belgie_base_url: str,
    *,
    requested_resource: str | None,
    bound_resource: str | None = None,
    require_bound_match: bool = False,
) -> tuple[str | None, JSONResponse | None]:
    configured_resource = settings.resolve_resource(belgie_base_url)
    configured_resource_url = str(configured_resource[0]) if configured_resource is not None else None
    canonical_bound_resource = bound_resource
    if (
        configured_resource_url is not None
        and bound_resource is not None
        and _resource_urls_match(configured_resource_url, bound_resource)
    ):
        canonical_bound_resource = configured_resource_url

    if requested_resource is not None:
        if configured_resource_url is None:
            return None, _oauth_error("invalid_target", status_code=status.HTTP_400_BAD_REQUEST)
        if not _resource_urls_match(configured_resource_url, requested_resource):
            return None, _oauth_error("invalid_target", status_code=status.HTTP_400_BAD_REQUEST)
        requested_resource = configured_resource_url

    if require_bound_match and requested_resource is not None and bound_resource is None:
        return None, _oauth_error("invalid_target", status_code=status.HTTP_400_BAD_REQUEST)
    if (
        canonical_bound_resource is not None
        and requested_resource is not None
        and not _resource_urls_match(requested_resource, canonical_bound_resource)
    ):
        return None, _oauth_error("invalid_target", status_code=status.HTTP_400_BAD_REQUEST)

    if canonical_bound_resource is not None:
        return canonical_bound_resource, None
    return requested_resource, None


def _build_access_token_audience(
    issuer_url: str,
    *,
    base_resource: str | None,
    scopes: list[str],
) -> str | list[str] | None:
    if base_resource is None:
        return None
    if "openid" not in scopes:
        return base_resource
    userinfo_audience = join_url(issuer_url, "userinfo")
    return [base_resource, userinfo_audience]


def _decode_unverified_jwt(token: str) -> dict[str, JSONValue] | None:
    try:
        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except InvalidTokenError:
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
