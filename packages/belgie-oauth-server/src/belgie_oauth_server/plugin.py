import base64
import binascii
import hashlib
import inspect
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, Protocol
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

from belgie_oauth_server.client import OAuthLoginIntent, OAuthServerClient
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
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthErrorResponse,
    OAuthIntrospectionResponse,
    OAuthMetadata,
    OAuthToken,
    OIDCMetadata,
    ProtectedResourceMetadata,
    UserInfoResponse,
)
from belgie_oauth_server.provider import AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import construct_redirect_uri, create_code_challenge, join_url

_ROOT_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
ACCESS_TOKEN_HINT = "access_token"  # noqa: S105
REFRESH_TOKEN_HINT = "refresh_token"  # noqa: S105
BEARER_TOKEN_TYPE = "Bearer"  # noqa: S105
REFRESH_TOKEN_TYPE = "refresh_token"  # noqa: S105
type JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
type FormValue = str | UploadFile
type FormInput = Mapping[str, FormValue] | FormData
type AuthorizePrompt = Literal["none", "consent", "login", "create", "select_account"]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


@dataclass(frozen=True, slots=True, kw_only=True)
class _TokenHandlerContext:
    client: BelgieClient
    form: FormInput
    provider: SimpleOAuthProvider
    settings: OAuthServer
    belgie_base_url: str
    issuer_url: str
    fallback_signing_secret: str
    client_id: str | None
    client_secret: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _AuthorizeRequestContext:
    oauth_client: OAuthClientInformationFull
    params: AuthorizationParams
    prompt_values: frozenset[AuthorizePrompt]
    redirect_uri: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _InteractionError:
    error: str
    description: str


class OAuthServerPlugin(PluginClient):
    def __init__(self, _belgie_settings: BelgieSettings, settings: OAuthServer) -> None:
        self._settings = settings
        self._provider: SimpleOAuthProvider | None = None
        self._metadata_router: APIRouter | None = None
        self._resolve_client: Callable[..., Coroutine[object, object, OAuthServerClient]] | None = None

    @property
    def settings(self) -> OAuthServer:
        return self._settings

    @property
    def provider(self) -> SimpleOAuthProvider | None:
        return self._provider

    def _ensure_dependency_resolver(self, belgie: Belgie, provider: SimpleOAuthProvider, issuer_url: str) -> None:
        if self._resolve_client is not None:
            return

        async def resolve_client(_client: Annotated[BelgieClient, Depends(belgie)]) -> OAuthServerClient:
            return OAuthServerClient(provider=provider, issuer_url=issuer_url)

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    async def __call__(self, *args: object, **kwargs: object) -> OAuthServerClient:
        if self._resolve_client is None:
            msg = (
                "OAuthServerPlugin dependency requires router initialization "
                "(call app.include_router(belgie.router) first)"
            )
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    def router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )
        if self._provider is None:
            self._provider = SimpleOAuthProvider(
                self._settings,
                issuer_url=issuer_url,
                database_factory=belgie.database,
            )
        provider = self._provider
        self._ensure_dependency_resolver(belgie, provider, issuer_url)

        self._metadata_router = self.metadata_router(belgie)

        router = APIRouter(prefix=self._settings.prefix, tags=["oauth"])
        metadata = build_oauth_metadata(issuer_url, self._settings)
        openid_metadata = build_openid_metadata(issuer_url, self._settings)

        router = self._add_metadata_route(router, metadata)
        router = self._add_openid_metadata_route(router, openid_metadata)
        router = self._add_authorize_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_token_route(router, belgie, provider, self._settings, belgie.settings.base_url, issuer_url)
        router = self._add_register_route(router, belgie, provider, self._settings)
        router = self._add_revoke_route(router, provider)
        router = self._add_userinfo_route(router, belgie, provider)
        router = self._add_end_session_route(router, belgie, provider, issuer_url)
        router = self._add_login_route(router, belgie, issuer_url, self._settings, provider)
        router = self._add_continue_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_consent_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_login_callback_route(router, belgie, provider, self._settings, issuer_url)
        return self._add_introspect_route(router, provider)

    def metadata_router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )
        metadata = build_oauth_metadata(issuer_url, self._settings)
        well_known_path = build_oauth_metadata_well_known_path(issuer_url)

        openid_metadata = build_openid_metadata(issuer_url, self._settings)
        openid_well_known_path = build_openid_metadata_well_known_path(issuer_url)

        router = APIRouter(tags=["oauth"])

        async def metadata_handler(_: Request) -> OAuthMetadata:
            return metadata

        async def openid_metadata_handler(_: Request) -> OIDCMetadata:
            return openid_metadata

        router.add_api_route(
            well_known_path,
            metadata_handler,
            methods=["GET"],
            response_model=OAuthMetadata,
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
                response_model=OAuthMetadata,
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
    def _add_metadata_route(router: APIRouter, metadata: OAuthMetadata) -> APIRouter:
        async def metadata_handler(_: Request) -> OAuthMetadata:
            return metadata

        router.add_api_route(
            "/.well-known/oauth-authorization-server",
            metadata_handler,
            methods=["GET"],
            response_model=OAuthMetadata,
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
    def _add_authorize_route(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
        issuer_url: str,
    ) -> APIRouter:
        async def _authorize(  # noqa: PLR0911
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
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
                    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)
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
                return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)

            if settings.consent_url is None:
                await provider.save_consent(
                    authorize_request.oauth_client.client_id or settings.client_id,
                    str(individual.id),
                    params_with_principal.scopes or [settings.default_scope],
                )
            state_value = await _authorize_state(provider, authorize_request.oauth_client, params_with_principal)
            redirect_url = await _issue_authorization_code(provider, state_value, issuer_url)
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        async def authorize_get_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
            return await _authorize(request, client)

        async def authorize_post_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
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
    ) -> APIRouter:
        async def token_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> OAuthToken | Response:
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
                fallback_signing_secret=belgie.settings.secret,
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

        router.add_api_route("/token", token_handler, methods=["POST"], response_model=OAuthToken)
        return router

    @staticmethod
    def _add_register_route(
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServer,
    ) -> APIRouter:
        async def register_handler(  # noqa: PLR0911
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> OAuthClientInformationFull | Response:
            if not settings.allow_dynamic_client_registration:
                return _oauth_error(
                    "access_denied",
                    "client registration is disabled",
                    status_code=status.HTTP_403_FORBIDDEN,
                )

            try:
                payload = await request.json()
                metadata = OAuthClientMetadata.model_validate(payload)
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

            token_endpoint_auth_method = metadata.token_endpoint_auth_method or "client_secret_post"
            if not authenticated and token_endpoint_auth_method != "none":  # noqa: S105
                return _oauth_error(
                    "invalid_request",
                    "authentication required for confidential client registration",
                    status_code=status.HTTP_401_UNAUTHORIZED,
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
            return JSONResponse(
                client_info.model_dump(mode="json", exclude_none=True),
                status_code=status.HTTP_201_CREATED,
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                },
            )

        router.add_api_route(
            "/register",
            register_handler,
            methods=["POST"],
            response_model=OAuthClientInformationFull,
            status_code=status.HTTP_201_CREATED,
        )
        return router

    @staticmethod
    def _add_revoke_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:  # noqa: C901
        async def revoke_handler(request: Request) -> Response:  # noqa: C901, PLR0911
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
    def _add_userinfo_route(router: APIRouter, belgie: Belgie, provider: SimpleOAuthProvider) -> APIRouter:
        async def userinfo_handler(  # noqa: PLR0911
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> UserInfoResponse | Response:
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

            access_token = await provider.load_access_token(token_value)
            if access_token is None:
                return _oauth_error("invalid_token", status_code=status.HTTP_401_UNAUTHORIZED)

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
            subject_identifier = (
                provider.resolve_subject_identifier(oauth_client, access_token.individual_id)
                if oauth_client is not None
                else access_token.individual_id
            )

            return UserInfoResponse.model_validate(
                _build_user_claims(
                    user,
                    access_token.scopes,
                    subject_identifier=subject_identifier,
                ),
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
                # Pass 2: verify signature and standard claims with the resolved client.
                payload = jwt.decode(
                    id_token_hint,
                    _id_token_signing_key(
                        _resolve_id_token_signing_secret(oauth_client, belgie.settings.secret),
                    ),
                    algorithms=["HS256"],
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
                    return RedirectResponse(url=redirect_uri, status_code=status.HTTP_302_FOUND)

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
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

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
        async def _handle_continue(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
            payload = await _get_request_payload(request)
            state = _get_payload_str(payload, "state")
            if not state:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing state")

            created = _get_payload_bool(payload, "created")
            selected = _get_payload_bool(payload, "selected")
            if created is not True and selected is not True:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing parameters")

            try:
                individual = await client.get_individual(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc
                raise

            handled_prompt: AuthorizePrompt = "create" if created is True else "select_account"

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
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        async def continue_get_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
            return await _handle_continue(request, client)

        async def continue_post_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
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
        async def _handle_consent(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
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
                return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

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
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        async def consent_get_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> Response:
            return await _handle_consent(request, client)

        async def consent_post_handler(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
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
                redirect_url = await _resume_authorization_flow(
                    provider,
                    settings,
                    state,
                    handled_prompt=handled_prompt,
                    issuer_url=issuer_url,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        router.add_api_route("/login/callback", login_callback_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_introspect_route(  # noqa: C901
        router: APIRouter,
        provider: SimpleOAuthProvider,
    ) -> APIRouter:
        async def introspect_handler(request: Request) -> OAuthIntrospectionResponse | Response:  # noqa: C901, PLR0911
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
                return JSONResponse(
                    OAuthIntrospectionResponse(active=False).model_dump(mode="json"),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if token.startswith("Bearer "):
                token = token.removeprefix("Bearer ")

            token_type_hint, hint_error = _parse_token_type_hint(form)
            if hint_error is not None:
                return hint_error

            if token_type_hint in {None, ACCESS_TOKEN_HINT}:
                access_token = await provider.load_access_token(token)
                if access_token and access_token.client_id == oauth_client.client_id:
                    access_token_client = await provider.get_client(access_token.client_id)
                    subject_identifier = (
                        provider.resolve_subject_identifier(access_token_client, access_token.individual_id)
                        if access_token_client is not None and access_token.individual_id is not None
                        else access_token.individual_id
                    )
                    return OAuthIntrospectionResponse(
                        active=True,
                        client_id=access_token.client_id,
                        scope=" ".join(access_token.scopes),
                        exp=access_token.expires_at,
                        iat=access_token.created_at,
                        token_type=BEARER_TOKEN_TYPE,
                        aud=access_token.resource,
                        sub=subject_identifier,
                        sid=access_token.session_id,
                        iss=provider.issuer_url,
                    )
                if token_type_hint == ACCESS_TOKEN_HINT:
                    return OAuthIntrospectionResponse(active=False)

            if token_type_hint in {None, REFRESH_TOKEN_HINT}:
                refresh_token = await provider.load_refresh_token(token)
                if refresh_token and refresh_token.client_id == oauth_client.client_id:
                    refresh_token_client = await provider.get_client(refresh_token.client_id)
                    subject_identifier = (
                        provider.resolve_subject_identifier(refresh_token_client, refresh_token.individual_id)
                        if refresh_token_client is not None and refresh_token.individual_id is not None
                        else refresh_token.individual_id
                    )
                    return OAuthIntrospectionResponse(
                        active=True,
                        client_id=refresh_token.client_id,
                        scope=" ".join(refresh_token.scopes),
                        exp=refresh_token.expires_at,
                        iat=refresh_token.created_at,
                        token_type=REFRESH_TOKEN_TYPE,
                        aud=refresh_token.resource,
                        sub=subject_identifier,
                        sid=refresh_token.session_id,
                        iss=provider.issuer_url,
                    )

            return OAuthIntrospectionResponse(active=False)

        router.add_api_route(
            "/introspect",
            introspect_handler,
            methods=["POST"],
            response_model=OAuthIntrospectionResponse,
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
    if not oauth_client:
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
    oauth_client: OAuthClientInformationFull,
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


def _resolve_auth_redirect_url(settings: OAuthServer, belgie_base_url: str, *, intent: OAuthLoginIntent) -> str | None:
    if intent == "consent":
        return _resolve_redirect_url(belgie_base_url, settings.consent_url) if settings.consent_url else None
    if intent == "select_account":
        return (
            _resolve_redirect_url(belgie_base_url, settings.select_account_url) if settings.select_account_url else None
        )
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


def _derive_initial_intent(prompt_values: frozenset[AuthorizePrompt]) -> OAuthLoginIntent:
    if "create" in prompt_values:
        return "create"
    return "login"


def _pkce_requirement_for_client(
    oauth_client: OAuthClientInformationFull,
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
    oauth_client: OAuthClientInformationFull,
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
    oauth_client: OAuthClientInformationFull,
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
    if "consent" in prompt_values:
        return _InteractionError(error="consent_required", description="End-User consent is required")
    if await _consent_required(provider, settings, oauth_client, params):
        return _InteractionError(error="consent_required", description="End-User consent is required")
    return None


async def _resolve_next_interaction(  # noqa: PLR0913
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    oauth_client: OAuthClientInformationFull,
    params: AuthorizationParams,
    *,
    prompt_values: frozenset[AuthorizePrompt],
    allow_select_account_resolver: bool = True,
) -> OAuthLoginIntent | None:
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
    oauth_client: OAuthClientInformationFull,
    params: AuthorizationParams,
) -> bool:
    if params.individual_id is None:
        return False
    return not await provider.has_consent(
        oauth_client.client_id or settings.client_id,
        params.individual_id,
        params.scopes or [settings.default_scope],
    )


async def _select_account_required(
    settings: OAuthServer,
    oauth_client: OAuthClientInformationFull,
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


async def _resume_authorization_flow(
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    state: str,
    *,
    handled_prompt: AuthorizePrompt,
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
        await provider.save_consent(
            oauth_client.client_id or settings.client_id,
            state_data.individual_id,
            state_data.scopes or [settings.default_scope],
        )
    return await _issue_authorization_code(provider, state, issuer_url)


def _remove_prompt_value(prompt: str | None, value: AuthorizePrompt) -> str | None:
    prompt_values, prompt_error = _parse_prompt_values(prompt)
    if prompt_error is not None or not prompt_values:
        return None
    remaining_values = frozenset(existing for existing in prompt_values if existing != value)
    return _normalize_prompt_values(remaining_values)


def _build_interaction_return_to(issuer_url: str, state: str, intent: OAuthLoginIntent) -> str:
    if intent == "create":
        return construct_redirect_uri(join_url(issuer_url, "continue"), state=state, created="true")
    if intent == "select_account":
        return construct_redirect_uri(join_url(issuer_url, "continue"), state=state, selected="true")
    if intent == "consent":
        return construct_redirect_uri(join_url(issuer_url, "consent"), state=state)
    return construct_redirect_uri(join_url(issuer_url, "login/callback"), state=state)


def _oauth_error(
    error: str,
    description: str | None = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> JSONResponse:
    return JSONResponse(
        OAuthErrorResponse(
            error=error,
            error_description=description,
        ).model_dump(mode="json", exclude_none=True),
        status_code=status_code,
    )


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
) -> tuple[OAuthClientInformationFull | None, JSONResponse | None]:
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
) -> OAuthToken | Response:
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
    return OAuthToken.model_validate(
        {
            **token.model_dump(),
            "id_token": await _maybe_build_id_token(
                ctx.client,
                ctx.provider,
                ctx.settings,
                ctx.issuer_url,
                oauth_client,
                fallback_signing_secret=ctx.fallback_signing_secret,
                scopes=authorization_code.scopes,
                individual_id=authorization_code.individual_id,
                nonce=authorization_code.nonce,
                session_id=authorization_code.session_id,
            ),
        },
    )


async def _handle_refresh_token_grant(ctx: _TokenHandlerContext) -> OAuthToken | Response:  # noqa: C901, PLR0911
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

    return OAuthToken.model_validate(
        {
            **token.model_dump(),
            "id_token": await _maybe_build_id_token(
                ctx.client,
                ctx.provider,
                ctx.settings,
                ctx.issuer_url,
                oauth_client,
                fallback_signing_secret=ctx.fallback_signing_secret,
                scopes=scopes,
                individual_id=refresh_token.individual_id,
                session_id=refresh_token.session_id,
            ),
        },
    )


async def _handle_client_credentials_grant(ctx: _TokenHandlerContext) -> OAuthToken | Response:  # noqa: PLR0911
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
    scopes = requested_scopes or ctx.provider.default_scopes_for_client(oauth_client)
    try:
        ctx.provider.validate_scopes_for_client(oauth_client, scopes)
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
    return OAuthToken.model_validate(token.model_dump())


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


async def _maybe_build_id_token(  # noqa: PLR0913
    client: BelgieClient,
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    issuer_url: str,
    oauth_client: OAuthClientInformationFull,
    *,
    fallback_signing_secret: str,
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

    return _build_id_token(
        provider,
        settings,
        issuer_url,
        oauth_client,
        user=individual,
        scopes=scopes,
        fallback_signing_secret=fallback_signing_secret,
        nonce=nonce,
        session_id=session_id,
    )


def _build_id_token(  # noqa: PLR0913
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    issuer_url: str,
    oauth_client: OAuthClientInformationFull,
    *,
    user: _UserClaimsSource,
    scopes: list[str],
    fallback_signing_secret: str,
    nonce: str | None,
    session_id: str | None,
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
    }
    if nonce:
        payload["nonce"] = nonce
    if oauth_client.enable_end_session and session_id:
        payload["sid"] = session_id

    return jwt.encode(
        payload,
        _id_token_signing_key(_resolve_id_token_signing_secret(oauth_client, fallback_signing_secret)),
        algorithm="HS256",
    )


def _id_token_signing_key(signing_secret: str) -> bytes:
    return hashlib.sha256(signing_secret.encode("utf-8")).digest()


def _resolve_id_token_signing_secret(oauth_client: OAuthClientInformationFull, fallback_secret: str) -> str:
    if oauth_client.client_secret is not None:
        return oauth_client.client_secret
    if oauth_client.token_endpoint_auth_method != "none":  # noqa: S105
        msg = "confidential client is missing stored client_secret; re-register the client"
        raise OAuthError(msg)
    return fallback_secret


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
