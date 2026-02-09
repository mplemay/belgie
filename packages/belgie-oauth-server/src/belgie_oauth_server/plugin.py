from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from belgie_core.core.plugin import Plugin
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import SecurityScopes
from pydantic import AnyUrl, ValidationError

from belgie_oauth_server.metadata import (
    _ROOT_OAUTH_METADATA_PATH,
    build_oauth_metadata,
    build_oauth_metadata_well_known_path,
    build_protected_resource_metadata,
    build_protected_resource_metadata_well_known_path,
)
from belgie_oauth_server.models import (
    InvalidRedirectUriError,
    InvalidScopeError,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
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

        router = self._add_metadata_route(router, metadata)
        router = self._add_authorize_route(router, belgie, provider, self._settings, issuer_url)
        router = self._add_token_route(router, provider)
        router = self._add_register_route(router, provider)
        router = self._add_revoke_route(router, provider)
        router = self._add_login_route(router, belgie, issuer_url, self._settings)
        router = self._add_login_callback_route(router, belgie, provider)
        return self._add_introspect_route(router, provider)

    def metadata_router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )
        metadata = build_oauth_metadata(issuer_url, self._settings)
        well_known_path = build_oauth_metadata_well_known_path(issuer_url)
        router = APIRouter(tags=["oauth"])

        async def metadata_handler(_: Request) -> Response:
            return JSONResponse(metadata.model_dump(mode="json"))

        router.add_api_route(well_known_path, metadata_handler, methods=["GET"])

        if self._settings.include_root_oauth_metadata_fallback and well_known_path != _ROOT_OAUTH_METADATA_PATH:
            router.add_api_route(
                _ROOT_OAUTH_METADATA_PATH,
                metadata_handler,
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
                await client.get_user(SecurityScopes(), request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    if not settings.login_url:
                        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc

                    state_value = await _authorize_state(provider, oauth_client, params)
                    login_url = _build_login_redirect(issuer_url, state_value)
                    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)
                raise

            state_value = await _authorize_state(provider, oauth_client, params)
            redirect_url = await _issue_authorization_code(provider, state_value)
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        router.add_api_route("/authorize", authorize_handler, methods=["GET", "POST"])
        return router

    @staticmethod
    def _add_token_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:  # noqa: C901
        async def token_handler(request: Request) -> Response:  # noqa: C901, PLR0911
            form = await request.form()
            grant_type = _get_str(form, "grant_type")
            if grant_type != "authorization_code":
                return _oauth_error("unsupported_grant_type", status_code=400)

            code = _get_str(form, "code")
            if not code:
                return _oauth_error("invalid_request", "missing code", status_code=400)

            client_id = _get_str(form, "client_id")
            if not client_id:
                return _oauth_error("invalid_client", status_code=401)

            oauth_client = await provider.get_client(client_id)
            if not oauth_client:
                return _oauth_error("invalid_client", status_code=401)

            client_secret = _get_str(form, "client_secret")
            if oauth_client.client_secret and client_secret != oauth_client.client_secret:
                return _oauth_error("invalid_client", status_code=401)

            authorization_code = await provider.load_authorization_code(code)
            if not authorization_code:
                return _oauth_error("invalid_grant", status_code=400)

            if authorization_code.expires_at < time.time():
                return _oauth_error("invalid_grant", "code expired", status_code=400)

            redirect_uri_raw = _get_str(form, "redirect_uri")
            if client_id != authorization_code.client_id:
                return _oauth_error("invalid_grant", "client_id mismatch", status_code=400)

            if authorization_code.redirect_uri_provided_explicitly and not redirect_uri_raw:
                return _oauth_error("invalid_request", "missing redirect_uri", status_code=400)
            if redirect_uri_raw and redirect_uri_raw != str(authorization_code.redirect_uri):
                return _oauth_error("invalid_grant", "redirect_uri mismatch", status_code=400)

            code_verifier = _get_str(form, "code_verifier")
            if not code_verifier:
                return _oauth_error("invalid_request", "missing code_verifier", status_code=400)

            expected_challenge = create_code_challenge(code_verifier)
            if expected_challenge != authorization_code.code_challenge:
                return _oauth_error("invalid_grant", "invalid code_verifier", status_code=400)

            token = await provider.exchange_authorization_code(authorization_code)
            return JSONResponse(token.model_dump())

        router.add_api_route("/token", token_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_register_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:
        async def register_handler(request: Request) -> Response:
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

            try:
                client_info = await provider.register_client(metadata)
            except ValueError as exc:
                description = str(exc) or "invalid client metadata"
                return _oauth_error("invalid_request", description, status_code=400)
            return JSONResponse(client_info.model_dump(mode="json"))

        router.add_api_route("/register", register_handler, methods=["POST"])
        return router

    @staticmethod
    def _add_revoke_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:
        async def revoke_handler(request: Request) -> Response:
            form = await request.form()
            client_id: str | None = _get_str(form, "client_id")
            if not client_id:
                return _oauth_error("invalid_request", "missing client_id", status_code=400)

            oauth_client = await provider.get_client(client_id)
            if not oauth_client:
                return _oauth_error("invalid_client", status_code=401)

            client_secret: str | None = _get_str(form, "client_secret")
            if oauth_client.client_secret:
                if not client_secret:
                    return _oauth_error("invalid_request", "missing client_secret", status_code=400)
                if client_secret != oauth_client.client_secret:
                    return _oauth_error("invalid_client", status_code=401)

            token: str | None = _get_str(form, "token")
            if not token:
                return _oauth_error("invalid_request", "missing token", status_code=400)

            access_token = await provider.load_access_token(token)
            if access_token:
                await provider.revoke_token(access_token)
            return JSONResponse({})

        router.add_api_route("/revoke", revoke_handler, methods=["POST"])
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
            # Build a callback URL with state, then wrap it into the login redirect as return_to.
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
                await client.get_user(SecurityScopes(), request)
            except HTTPException as exc:
                if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required") from exc
                raise

            try:
                redirect_url = await provider.issue_authorization_code(state)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        router.add_api_route("/login/callback", login_callback_handler, methods=["GET"])
        return router

    @staticmethod
    def _add_introspect_route(router: APIRouter, provider: SimpleOAuthProvider) -> APIRouter:
        async def introspect_handler(request: Request) -> Response:
            form = await request.form()
            token = _get_str(form, "token")
            if not token:
                return JSONResponse({"active": False}, status_code=400)

            access_token = await provider.load_access_token(token)
            if not access_token:
                return JSONResponse({"active": False})

            return JSONResponse(
                {
                    "active": True,
                    "client_id": access_token.client_id,
                    "scope": " ".join(access_token.scopes),
                    "exp": access_token.expires_at,
                    "iat": access_token.created_at,
                    "token_type": "Bearer",
                    "aud": access_token.resource,
                },
            )

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
        return

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
