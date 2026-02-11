from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import jwt
from belgie_core.core.plugin import Plugin
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import SecurityScopes
from jwt import InvalidTokenError
from pydantic import AnyUrl, ValidationError

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
    InvalidScopeError,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OIDCMetadata,
)
from belgie_oauth_server.provider import AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServerSettings
from belgie_oauth_server.utils import construct_redirect_uri, create_code_challenge, join_url

if TYPE_CHECKING:
    from collections.abc import Mapping

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient
    from belgie_core.core.settings import BelgieSettings

_ROOT_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
ACCESS_TOKEN_HINT = "access_token"  # noqa: S105
REFRESH_TOKEN_HINT = "refresh_token"  # noqa: S105


@dataclass(frozen=True, slots=True, kw_only=True)
class _TokenHandlerContext:
    client: BelgieClient
    form: Mapping[str, Any]
    provider: SimpleOAuthProvider
    settings: OAuthServerSettings
    belgie_base_url: str
    issuer_url: str
    fallback_signing_secret: str
    client_id: str | None
    client_secret: str | None


class OAuthServerPlugin(Plugin[OAuthServerSettings]):
    def __init__(self, _belgie_settings: BelgieSettings, settings: OAuthServerSettings) -> None:
        self._settings = settings
        self._provider: SimpleOAuthProvider | None = None
        self._metadata_router: APIRouter | None = None

    def router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )
        if self._provider is None:
            self._provider = SimpleOAuthProvider(self._settings, issuer_url=issuer_url)
        provider = self._provider

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
        router = self._add_login_route(router, belgie, issuer_url, self._settings)
        router = self._add_login_callback_route(router, belgie, provider)
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

        async def metadata_handler(_: Request) -> Response:
            return JSONResponse(metadata.model_dump(mode="json"))

        async def openid_metadata_handler(_: Request) -> Response:
            return JSONResponse(openid_metadata.model_dump(mode="json"))

        router.add_api_route(well_known_path, metadata_handler, methods=["GET"])
        router.add_api_route(openid_well_known_path, openid_metadata_handler, methods=["GET"])

        if self._settings.include_root_oauth_metadata_fallback and well_known_path != _ROOT_OAUTH_METADATA_PATH:
            router.add_api_route(
                _ROOT_OAUTH_METADATA_PATH,
                metadata_handler,
                methods=["GET"],
            )

        if (
            self._settings.include_root_openid_metadata_fallback
            and openid_well_known_path != _ROOT_OPENID_METADATA_PATH
        ):
            router.add_api_route(
                _ROOT_OPENID_METADATA_PATH,
                openid_metadata_handler,
                methods=["GET"],
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

            async def protected_resource_metadata_handler(_: Request) -> Response:
                return JSONResponse(protected_resource_metadata.model_dump(mode="json"))

            router.add_api_route(
                protected_resource_well_known_path,
                protected_resource_metadata_handler,
                methods=["GET"],
            )

            if (
                self._settings.include_root_resource_metadata_fallback
                and protected_resource_well_known_path != _ROOT_RESOURCE_METADATA_PATH
            ):
                router.add_api_route(
                    _ROOT_RESOURCE_METADATA_PATH,
                    protected_resource_metadata_handler,
                    methods=["GET"],
                )

        return router

    def public(self, belgie: Belgie) -> APIRouter:
        if self._metadata_router is None:
            self._metadata_router = self.metadata_router(belgie)
        return self._metadata_router

    @staticmethod
    def _add_metadata_route(router: APIRouter, metadata: OAuthMetadata) -> APIRouter:
        async def metadata_handler(_: Request) -> Response:
            return JSONResponse(metadata.model_dump(mode="json"))

        router.add_api_route(
            "/.well-known/oauth-authorization-server",
            metadata_handler,
            methods=["GET"],
        )
        return router

    @staticmethod
    def _add_openid_metadata_route(router: APIRouter, metadata: OIDCMetadata) -> APIRouter:
        async def metadata_handler(_: Request) -> Response:
            return JSONResponse(metadata.model_dump(mode="json"))

        router.add_api_route(
            "/.well-known/openid-configuration",
            metadata_handler,
            methods=["GET"],
        )
        return router

    @staticmethod
    def _add_authorize_route(
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServerSettings,
        issuer_url: str,
    ) -> APIRouter:
        async def authorize_handler(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            data = await _get_request_params(request)
            oauth_client, params = await _parse_authorize_params(data, provider, settings, belgie.settings.base_url)

            try:
                user = await client.get_user(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    if not settings.login_url:
                        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc

                    state_value = await _authorize_state(provider, oauth_client, params)
                    login_url = _build_login_redirect(issuer_url, state_value)
                    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)
                raise

            params_with_principal = _with_authorization_principal(
                params,
                user_id=str(user.id),
                session_id=str(session.id),
            )
            state_value = await _authorize_state(provider, oauth_client, params_with_principal)
            redirect_url = await _issue_authorization_code(provider, state_value)
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        router.add_api_route("/authorize", authorize_handler, methods=["GET", "POST"])
        return router

    @staticmethod
    def _add_token_route(  # noqa: PLR0913
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServerSettings,
        belgie_base_url: str,
        issuer_url: str,
    ) -> APIRouter:
        async def token_handler(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
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

            return _oauth_error("unsupported_grant_type", status_code=400)

        router.add_api_route("/token", token_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_register_route(  # noqa: C901
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
        settings: OAuthServerSettings,
    ) -> APIRouter:
        async def register_handler(  # noqa: PLR0911
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            if not settings.allow_dynamic_client_registration:
                return _oauth_error(
                    "access_denied",
                    "client registration is disabled",
                    status_code=403,
                )

            try:
                payload = await request.json()
                metadata = OAuthClientMetadata.model_validate(payload)
            except ValidationError as exc:
                return _oauth_error(
                    "invalid_request",
                    _format_validation_error(exc),
                    status_code=400,
                )
            except ValueError as exc:
                description = str(exc) or "invalid client metadata"
                return _oauth_error("invalid_request", description, status_code=400)

            authenticated = False
            try:
                await client.get_user(SecurityScopes(), request)
                authenticated = True
            except HTTPException as exc:
                if exc.status_code != status.HTTP_401_UNAUTHORIZED:
                    raise

            is_public_client = (metadata.token_endpoint_auth_method or "client_secret_post") == "none"
            if not authenticated:
                if not settings.allow_unauthenticated_client_registration:
                    return _oauth_error(
                        "invalid_token",
                        "authentication required for client registration",
                        status_code=401,
                    )
                if not is_public_client:
                    return _oauth_error(
                        "invalid_request",
                        "authentication required for confidential client registration",
                        status_code=401,
                    )

            try:
                client_info = await provider.register_client(metadata)
            except ValueError as exc:
                description = str(exc) or "invalid client metadata"
                return _oauth_error("invalid_request", description, status_code=400)
            return JSONResponse(client_info.model_dump(mode="json"))

        router.add_api_route("/register", register_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_revoke_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:  # noqa: C901
        async def revoke_handler(request: Request) -> Response:  # noqa: C901
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

            token: str | None = _get_str(form, "token")
            if not token:
                return _oauth_error("invalid_request", "missing token", status_code=400)
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
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            authorization = request.headers.get("authorization")
            if not authorization:
                return _oauth_error("invalid_token", "authorization header not found", status_code=401)

            token_value = authorization.removeprefix("Bearer ").strip()
            if not token_value:
                return _oauth_error("invalid_token", "authorization header not found", status_code=401)

            access_token = await provider.load_access_token(token_value)
            if access_token is None:
                return _oauth_error("invalid_token", status_code=401)

            if "openid" not in access_token.scopes:
                return _oauth_error("invalid_scope", "Missing required scope", status_code=400)

            if access_token.user_id is None:
                return _oauth_error("invalid_request", "user not found", status_code=400)

            try:
                user_id = UUID(access_token.user_id)
            except ValueError:
                return _oauth_error("invalid_request", "user not found", status_code=400)

            user = await client.adapter.get_user_by_id(client.db, user_id)
            if user is None:
                return _oauth_error("invalid_request", "user not found", status_code=400)

            return JSONResponse(_build_user_claims(user, access_token.scopes))

        router.add_api_route("/userinfo", userinfo_handler, methods=["GET"])
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
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            id_token_hint = request.query_params.get("id_token_hint")
            if not id_token_hint:
                return _oauth_error("invalid_request", "missing id_token_hint", status_code=400)

            # Pass 1: decode without verification only to extract audience and identify
            # the candidate signing secret for full verification in pass 2 below.
            decoded_unverified = _decode_unverified_jwt(id_token_hint)
            if decoded_unverified is None:
                return _oauth_error("invalid_token", "invalid id token", status_code=401)

            requested_client_id = request.query_params.get("client_id")
            if requested_client_id is not None and not _aud_contains(
                decoded_unverified.get("aud"),
                requested_client_id,
            ):
                return _oauth_error("invalid_request", "audience mismatch", status_code=400)

            inferred_client_id = requested_client_id or _first_aud(decoded_unverified.get("aud"))
            if not inferred_client_id:
                return _oauth_error("invalid_request", "id token missing audience", status_code=400)

            oauth_client = await provider.get_client(inferred_client_id)
            if oauth_client is None:
                return _oauth_error("invalid_client", "client doesn't exist", status_code=400)
            if oauth_client.enable_end_session is not True:
                return _oauth_error("invalid_client", "client unable to logout", status_code=401)
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
                return _oauth_error("invalid_token", "invalid id token", status_code=401)

            sid = payload.get("sid")
            if not isinstance(sid, str) or not sid:
                return _oauth_error("invalid_request", "id token missing session", status_code=400)

            try:
                session_id = UUID(sid)
            except ValueError:
                return _oauth_error("invalid_request", "id token missing session", status_code=400)

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
        settings: OAuthServerSettings,
    ) -> APIRouter:
        async def login_handler(request: Request) -> Response:
            state = request.query_params.get("state")
            if not state:
                raise HTTPException(status_code=400, detail="missing state")

            if not settings.login_url:
                raise HTTPException(status_code=400, detail="login_url not configured")

            parsed_login_url = urlparse(settings.login_url)
            if parsed_login_url.scheme in {"http", "https"}:
                login_url = settings.login_url
            else:
                login_url = join_url(belgie.settings.base_url, settings.login_url)

            return_to_base = join_url(issuer_url, "login/callback")
            return_to_url = construct_redirect_uri(return_to_base, state=state)
            redirect_url = construct_redirect_uri(login_url, return_to=return_to_url)
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        router.add_api_route("/login", login_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_login_callback_route(
        router: APIRouter,
        belgie: Belgie,
        provider: SimpleOAuthProvider,
    ) -> APIRouter:
        async def login_callback_handler(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            state = request.query_params.get("state")
            if not state:
                raise HTTPException(status_code=400, detail="missing state")

            try:
                user = await client.get_user(SecurityScopes(), request)
                session = await client.get_session(request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc
                raise

            try:
                await provider.bind_authorization_state(state, user_id=str(user.id), session_id=str(session.id))
                redirect_url = await provider.issue_authorization_code(state)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        router.add_api_route("/login/callback", login_callback_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_introspect_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:  # noqa: C901
        async def introspect_handler(request: Request) -> Response:  # noqa: C901, PLR0911
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

            token = _get_str(form, "token")
            if not token:
                return JSONResponse({"active": False}, status_code=400)
            if token.startswith("Bearer "):
                token = token.removeprefix("Bearer ")

            token_type_hint, hint_error = _parse_token_type_hint(form)
            if hint_error is not None:
                return hint_error

            if token_type_hint in {None, ACCESS_TOKEN_HINT}:
                access_token = await provider.load_access_token(token)
                if access_token and access_token.client_id == oauth_client.client_id:
                    payload: dict[str, Any] = {
                        "active": True,
                        "client_id": access_token.client_id,
                        "scope": " ".join(access_token.scopes),
                        "exp": access_token.expires_at,
                        "iat": access_token.created_at,
                        "token_type": "Bearer",
                    }
                    if access_token.resource is not None:
                        payload["aud"] = access_token.resource
                    return JSONResponse(payload)
                if token_type_hint == ACCESS_TOKEN_HINT:
                    return JSONResponse({"active": False})

            if token_type_hint in {None, REFRESH_TOKEN_HINT}:
                refresh_token = await provider.load_refresh_token(token)
                if refresh_token and refresh_token.client_id == oauth_client.client_id:
                    payload: dict[str, Any] = {
                        "active": True,
                        "client_id": refresh_token.client_id,
                        "scope": " ".join(refresh_token.scopes),
                        "exp": refresh_token.expires_at,
                        "iat": refresh_token.created_at,
                        "token_type": "refresh_token",
                    }
                    if refresh_token.resource is not None:
                        payload["aud"] = refresh_token.resource
                    return JSONResponse(payload)

            return JSONResponse({"active": False})

        router.add_api_route("/introspect", introspect_handler, methods=["POST"])
        return router


def _build_issuer_url(belgie: Belgie, settings: OAuthServerSettings) -> str:
    parsed = urlparse(belgie.settings.base_url)
    base_path = parsed.path.rstrip("/")
    prefix = settings.prefix.strip("/")
    auth_path = "auth"
    full_path = f"{base_path}/{auth_path}/{prefix}" if prefix else f"{base_path}/{auth_path}"
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))


async def _parse_authorize_params(
    data: dict[str, str],
    provider: SimpleOAuthProvider,
    settings: OAuthServerSettings,
    belgie_base_url: str,
) -> tuple[OAuthClientInformationFull, AuthorizationParams]:
    response_type = _get_str(data, "response_type")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")

    client_id = _get_str(data, "client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="missing client_id")

    oauth_client = await provider.get_client(client_id)
    if not oauth_client:
        raise HTTPException(status_code=400, detail="invalid_client")

    redirect_uri_raw = _get_str(data, "redirect_uri")
    redirect_uri = AnyUrl(redirect_uri_raw) if redirect_uri_raw else None
    try:
        validated_redirect_uri = oauth_client.validate_redirect_uri(redirect_uri)
    except InvalidRedirectUriError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    scope_raw = _get_str(data, "scope")
    try:
        scopes = oauth_client.validate_scope(scope_raw)
    except InvalidScopeError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    if scopes is None:
        scopes = [settings.default_scope]

    code_challenge = _get_str(data, "code_challenge")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="missing code_challenge")

    code_challenge_method = _get_str(data, "code_challenge_method") or settings.code_challenge_method
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="unsupported code_challenge_method")

    resource = _get_str(data, "resource")
    _validate_authorize_resource(settings, belgie_base_url, resource)

    state = _get_str(data, "state") or secrets.token_hex(16)

    params = AuthorizationParams(
        state=state,
        scopes=scopes,
        code_challenge=code_challenge,
        redirect_uri=validated_redirect_uri,
        redirect_uri_provided_explicitly=redirect_uri_raw is not None,
        resource=resource,
        nonce=_get_str(data, "nonce"),
    )
    return oauth_client, params


def _validate_authorize_resource(
    settings: OAuthServerSettings,
    belgie_base_url: str,
    resource: str | None,
) -> None:
    if resource is None:
        return

    configured_resource = settings.resolve_resource(belgie_base_url)
    if configured_resource is None:
        raise HTTPException(status_code=400, detail="invalid_target")

    resource_url, _resource_scopes = configured_resource
    if resource != str(resource_url):
        raise HTTPException(status_code=400, detail="invalid_target")


async def _authorize_state(
    provider: SimpleOAuthProvider,
    oauth_client: OAuthClientInformationFull,
    params: AuthorizationParams,
) -> str:
    try:
        return await provider.authorize(oauth_client, params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _issue_authorization_code(provider: SimpleOAuthProvider, state: str) -> str:
    try:
        return await provider.issue_authorization_code(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _build_login_redirect(issuer_url: str, state: str) -> str:
    return construct_redirect_uri(join_url(issuer_url, "login"), state=state)


def _oauth_error(error: str, description: str | None = None, status_code: int = 400) -> JSONResponse:
    payload: dict[str, Any] = {"error": error}
    if description:
        payload["error_description"] = description
    return JSONResponse(payload, status_code=status_code)


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
    return dict(await request.form())


def _get_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    return None


def _extract_client_credentials(
    request: Request,
    form: Mapping[str, Any],
) -> tuple[str | None, str | None, JSONResponse | None]:
    client_id = _get_str(form, "client_id")
    client_secret = _get_str(form, "client_secret")
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Basic "):
        try:
            basic_client_id, basic_client_secret = _parse_basic_authorization(authorization)
        except ValueError:
            return None, None, _oauth_error("invalid_client", status_code=401)
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


async def _authenticate_client(  # noqa: PLR0911
    provider: SimpleOAuthProvider,
    client_id: str | None,
    client_secret: str | None,
    *,
    require_credentials: bool = False,
    require_confidential: bool = False,
) -> tuple[OAuthClientInformationFull | None, JSONResponse | None]:
    if not client_id:
        return None, _oauth_error("invalid_client", status_code=401)

    oauth_client = await provider.get_client(client_id)
    if not oauth_client:
        return None, _oauth_error("invalid_client", status_code=401)

    if oauth_client.client_secret is None:
        if require_credentials or require_confidential:
            return None, _oauth_error("invalid_client", status_code=401)
        if client_secret:
            return None, _oauth_error("invalid_client", status_code=401)
        return oauth_client, None

    if not client_secret:
        return None, _oauth_error("invalid_client", status_code=401)
    if not hmac.compare_digest(client_secret, oauth_client.client_secret):
        return None, _oauth_error("invalid_client", status_code=401)
    return oauth_client, None


async def _handle_authorization_code_grant(ctx: _TokenHandlerContext) -> Response:  # noqa: C901, PLR0911
    oauth_client, error = await _authenticate_client(
        ctx.provider,
        ctx.client_id,
        ctx.client_secret,
    )
    if error is not None:
        return error

    code = _get_str(ctx.form, "code")
    if not code:
        return _oauth_error("invalid_request", "missing code", status_code=400)

    authorization_code = await ctx.provider.load_authorization_code(code)
    if not authorization_code:
        return _oauth_error("invalid_grant", status_code=400)

    if authorization_code.expires_at < time.time():
        return _oauth_error("invalid_grant", "code expired", status_code=400)

    if oauth_client.client_id != authorization_code.client_id:
        return _oauth_error("invalid_grant", "client_id mismatch", status_code=400)

    redirect_uri_raw = _get_str(ctx.form, "redirect_uri")
    if authorization_code.redirect_uri_provided_explicitly and not redirect_uri_raw:
        return _oauth_error("invalid_request", "missing redirect_uri", status_code=400)
    if redirect_uri_raw and redirect_uri_raw != str(authorization_code.redirect_uri):
        return _oauth_error("invalid_grant", "redirect_uri mismatch", status_code=400)

    code_verifier = _get_str(ctx.form, "code_verifier")
    if not code_verifier:
        return _oauth_error("invalid_request", "missing code_verifier", status_code=400)

    expected_challenge = create_code_challenge(code_verifier)
    if expected_challenge != authorization_code.code_challenge:
        return _oauth_error("invalid_grant", "invalid code_verifier", status_code=400)

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
    token_payload = token.model_dump()
    token_payload["id_token"] = await _maybe_build_id_token(
        ctx.client,
        ctx.settings,
        ctx.issuer_url,
        oauth_client,
        fallback_signing_secret=ctx.fallback_signing_secret,
        scopes=authorization_code.scopes,
        user_id=authorization_code.user_id,
        nonce=authorization_code.nonce,
        session_id=authorization_code.session_id,
    )
    return JSONResponse(token_payload)


async def _handle_refresh_token_grant(ctx: _TokenHandlerContext) -> Response:  # noqa: C901, PLR0911
    oauth_client, error = await _authenticate_client(
        ctx.provider,
        ctx.client_id,
        ctx.client_secret,
    )
    if error is not None:
        return error

    refresh_token_value = _get_str(ctx.form, "refresh_token")
    if not refresh_token_value:
        return _oauth_error("invalid_request", "missing refresh_token", status_code=400)

    refresh_token = await ctx.provider.load_refresh_token(refresh_token_value)
    if not refresh_token:
        return _oauth_error("invalid_grant", status_code=400)

    if refresh_token.client_id != oauth_client.client_id:
        return _oauth_error("invalid_grant", "client_id mismatch", status_code=400)

    requested_scopes = _parse_scope_param(_get_str(ctx.form, "scope"))
    if requested_scopes is not None and not requested_scopes:
        return _oauth_error("invalid_scope", "missing scope", status_code=400)
    scopes = requested_scopes or refresh_token.scopes
    if requested_scopes is not None:
        invalid_scopes = [scope for scope in requested_scopes if scope not in refresh_token.scopes]
        if invalid_scopes:
            return _oauth_error(
                "invalid_scope",
                f"unable to issue scope {invalid_scopes[0]}",
                status_code=400,
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
        return _oauth_error("invalid_scope", str(exc), status_code=400)

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
        return _oauth_error("invalid_grant", str(exc), status_code=400)

    token_payload = token.model_dump()
    token_payload["id_token"] = await _maybe_build_id_token(
        ctx.client,
        ctx.settings,
        ctx.issuer_url,
        oauth_client,
        fallback_signing_secret=ctx.fallback_signing_secret,
        scopes=scopes,
        user_id=refresh_token.user_id,
        session_id=refresh_token.session_id,
    )
    return JSONResponse(token_payload)


async def _handle_client_credentials_grant(ctx: _TokenHandlerContext) -> Response:
    oauth_client, error = await _authenticate_client(
        ctx.provider,
        ctx.client_id,
        ctx.client_secret,
        require_confidential=True,
    )
    if error is not None:
        return error

    requested_scopes = _parse_scope_param(_get_str(ctx.form, "scope"))
    if requested_scopes is not None and not requested_scopes:
        return _oauth_error("invalid_scope", "missing scope", status_code=400)
    scopes = requested_scopes or ctx.provider.default_scopes_for_client(oauth_client)
    try:
        ctx.provider.validate_scopes_for_client(oauth_client, scopes)
    except ValueError as exc:
        return _oauth_error("invalid_scope", str(exc), status_code=400)

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
    return JSONResponse(token.model_dump())


def _parse_scope_param(scope: str | None) -> list[str] | None:
    if scope is None:
        return None
    parts = [segment for segment in scope.split(" ") if segment]
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return deduped


def _parse_token_type_hint(form: Mapping[str, Any]) -> tuple[str | None, JSONResponse | None]:
    token_type_hint = _get_str(form, "token_type_hint")
    if token_type_hint is None:
        return None, None
    if token_type_hint not in {ACCESS_TOKEN_HINT, REFRESH_TOKEN_HINT}:
        return None, _oauth_error("invalid_request", "unsupported token_type_hint", status_code=400)
    return token_type_hint, None


class _UserClaimsSource(Protocol):
    id: Any
    name: str | None
    image: str | None
    email: str
    email_verified: bool


def _build_user_claims(user: _UserClaimsSource, scopes: list[str]) -> dict[str, Any]:
    name_parts = [value for value in (user.name or "").split(" ") if value]
    payload: dict[str, Any] = {"sub": str(user.id)}

    if "profile" in scopes:
        payload.update(
            {
                "name": user.name or None,
                "picture": user.image or None,
                "given_name": " ".join(name_parts[:-1]) if len(name_parts) > 1 else None,
                "family_name": name_parts[-1] if len(name_parts) > 1 else None,
            },
        )
        payload = {key: value for key, value in payload.items() if value is not None}

    if "email" in scopes:
        payload["email"] = user.email
        payload["email_verified"] = user.email_verified

    return payload


async def _maybe_build_id_token(  # noqa: PLR0913
    client: BelgieClient,
    settings: OAuthServerSettings,
    issuer_url: str,
    oauth_client: OAuthClientInformationFull,
    *,
    fallback_signing_secret: str,
    scopes: list[str],
    user_id: str | None,
    nonce: str | None = None,
    session_id: str | None = None,
) -> str | None:
    if "openid" not in scopes:
        return None
    if user_id is None:
        return None

    try:
        parsed_user_id = UUID(user_id)
    except ValueError:
        return None

    user = await client.adapter.get_user_by_id(client.db, parsed_user_id)
    if user is None:
        return None

    return _build_id_token(
        settings,
        issuer_url,
        oauth_client,
        user=user,
        scopes=scopes,
        fallback_signing_secret=fallback_signing_secret,
        nonce=nonce,
        session_id=session_id,
    )


def _build_id_token(  # noqa: PLR0913
    settings: OAuthServerSettings,
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
    payload: dict[str, Any] = {
        **_build_user_claims(user, scopes),
        "iss": issuer_url,
        "sub": str(user.id),
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
    return fallback_secret


def _with_authorization_principal(params: AuthorizationParams, *, user_id: str, session_id: str) -> AuthorizationParams:
    return replace(
        params,
        user_id=user_id,
        session_id=session_id,
    )


def _resolve_token_resource(
    settings: OAuthServerSettings,
    belgie_base_url: str,
    *,
    requested_resource: str | None,
    bound_resource: str | None = None,
    require_bound_match: bool = False,
) -> tuple[str | None, JSONResponse | None]:
    configured_resource = settings.resolve_resource(belgie_base_url)

    if requested_resource is not None:
        if configured_resource is None:
            return None, _oauth_error("invalid_target", status_code=400)
        resource_url, _resource_scopes = configured_resource
        if requested_resource != str(resource_url):
            return None, _oauth_error("invalid_target", status_code=400)

    if require_bound_match and requested_resource is not None and bound_resource is None:
        return None, _oauth_error("invalid_target", status_code=400)
    if bound_resource is not None and requested_resource is not None and requested_resource != bound_resource:
        return None, _oauth_error("invalid_target", status_code=400)

    if bound_resource is not None:
        return bound_resource, None
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


def _decode_unverified_jwt(token: str) -> dict[str, Any] | None:
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


def _aud_contains(aud: Any, value: str) -> bool:  # noqa: ANN401
    if isinstance(aud, str):
        return aud == value
    if isinstance(aud, list):
        return value in aud
    return False


def _first_aud(aud: Any) -> str | None:  # noqa: ANN401
    if isinstance(aud, str):
        return aud
    if isinstance(aud, list) and aud:
        first = aud[0]
        if isinstance(first, str):
            return first
    return None
