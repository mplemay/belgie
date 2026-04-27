from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ClassVar, NoReturn, Protocol
from urllib.parse import urlparse, urlunparse

from belgie_core.core.client import BelgieClient  # noqa: TC002
from belgie_core.core.exceptions import OAuthError
from belgie_core.core.plugin import PluginClient
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes

from belgie_oauth._account_cookie import OAuthAccountCookieStore
from belgie_oauth._config import OAuthProvider
from belgie_oauth._errors import OAuthCallbackError
from belgie_oauth._flow import OAuthFlowCoordinator
from belgie_oauth._helpers import (
    OAuthTokenCodec,
    SecretBox,
    build_provider_callback_url,
    build_provider_start_url,
    coerce_optional_str,
)
from belgie_oauth._models import (
    ConsumedOAuthState,
    OAuthLinkedAccount,
    OAuthTokenSet,
    OAuthUserInfo,
    ResponseCookie,
)
from belgie_oauth._schemas import (
    OAuthAccountInfoResponse,
    OAuthAccountListResponse,
    OAuthAccountResponse,
    OAuthIdTokenRequest,
    OAuthProviderAccountRequest,
    OAuthRefreshTokenResponse,
    OAuthSessionSignInResponse,
    OAuthStatusResponse,
    OAuthTokenResponse,
    OAuthUserInfoResponse,
)
from belgie_oauth._state import build_state_store
from belgie_oauth._transport import OAuthTransport

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from belgie_core.core.settings import BelgieSettings

    from belgie_oauth._types import (
        JSONValue,
        OAuthBelgieRuntime,
        OAuthFlowIntent,
        OAuthResponseMode,
        OAuthStartPayload,
        ProviderMetadata,
    )


class OAuthSettings[P: PluginClient](Protocol):
    @property
    def to_provider(self) -> OAuthProvider: ...


def _raise_oauth_http_error(exc: OAuthError) -> NoReturn:
    detail = exc.code if isinstance(exc, OAuthCallbackError) else str(exc)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc


def _require_account_info(user_info: OAuthUserInfo | None) -> OAuthUserInfo:
    if user_info is not None:
        return user_info
    msg = "oauth account info not found"
    raise OAuthError(msg)


@dataclass(slots=True, kw_only=True)
class OAuthClient:
    plugin: OAuthPlugin
    client: BelgieClient
    request: Request | None = None
    response: Response | None = None

    async def signin_url(  # noqa: PLR0913
        self,
        *,
        success_redirect_url: str | None = None,
        return_to: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: JSONValue = None,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
        request_sign_up: bool = False,
    ) -> str:
        redirect_target = success_redirect_url if success_redirect_url is not None else return_to
        return await self.plugin.start_authorization(
            self.client,
            intent="signin",
            redirect_url=redirect_target,
            error_redirect_url=error_redirect_url,
            new_user_redirect_url=new_user_redirect_url,
            payload=payload,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
            request_sign_up=request_sign_up,
        )

    async def link_url(  # noqa: PLR0913
        self,
        *,
        individual_id: UUID,
        success_redirect_url: str | None = None,
        return_to: str | None = None,
        error_redirect_url: str | None = None,
        payload: JSONValue = None,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
    ) -> str:
        redirect_target = success_redirect_url if success_redirect_url is not None else return_to
        return await self.plugin.start_authorization(
            self.client,
            intent="link",
            individual_id=individual_id,
            redirect_url=redirect_target,
            error_redirect_url=error_redirect_url,
            payload=payload,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
        )

    async def list_accounts(self, *, individual_id: UUID) -> list[OAuthLinkedAccount]:
        return await self.plugin.list_accounts(self.client, individual_id=individual_id)

    async def token_set(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
        auto_refresh: bool = True,
    ) -> OAuthTokenSet:
        return await self.plugin.token_set(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
            request=self.request,
            response=self.response,
        )

    async def get_access_token(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
        auto_refresh: bool = True,
    ) -> str:
        token_set = await self.token_set(
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
        )
        if token_set.access_token is None:
            msg = "oauth account does not have an access token"
            raise OAuthError(msg)
        return token_set.access_token

    async def refresh_account(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
    ) -> OAuthLinkedAccount:
        return await self.plugin.refresh_account(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            request=self.request,
            response=self.response,
        )

    async def account_info(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
        auto_refresh: bool = True,
    ) -> OAuthUserInfo | None:
        return await self.plugin.account_info(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
            request=self.request,
            response=self.response,
        )

    async def unlink_account(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
    ) -> bool:
        return await self.plugin.unlink_account(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            request=self.request,
            response=self.response,
        )


class OAuthPlugin(PluginClient):
    client_type: ClassVar[type[OAuthClient]] = OAuthClient

    def __init__(
        self,
        belgie_settings: BelgieSettings,
        settings: OAuthSettings[OAuthPlugin],
    ) -> None:
        self.settings = settings
        self.config = settings.to_provider
        self._redirect_uri = build_provider_callback_url(
            belgie_settings.base_url,
            provider_id=self.provider_id,
        )
        self._resolve_client: Callable[..., OAuthClient] | None = None
        self._base_url = belgie_settings.base_url
        parsed_base_url = urlparse(belgie_settings.base_url)
        self._base_url_origin = (parsed_base_url.scheme.lower(), parsed_base_url.netloc.lower())
        self._start_box = SecretBox(secret=belgie_settings.secret, label="oauth redirect start")
        encryption_secret = (
            self.config.token_encryption_secret.get_secret_value()
            if self.config.token_encryption_secret is not None
            else belgie_settings.secret
        )
        self._transport = OAuthTransport(self.config, redirect_uri=self.redirect_uri)
        self._state_store = build_state_store(
            provider_id=self.provider_id,
            strategy=self.config.state_strategy,
            cookie_settings=belgie_settings.cookie,
            secret=belgie_settings.secret,
        )
        self._account_cookie_store = OAuthAccountCookieStore.from_settings(
            provider_id=self.provider_id,
            settings=belgie_settings,
        )
        self._flow = OAuthFlowCoordinator(
            config=self.config,
            provider_id=self.provider_id,
            transport=self._transport,
            state_store=self._state_store,
            token_codec=OAuthTokenCodec(enabled=self.config.encrypt_tokens, secret=encryption_secret),
            account_cookie_store=self._account_cookie_store,
        )

    @property
    def provider_id(self) -> str:
        return self.config.provider_id

    @property
    def redirect_uri(self) -> str:
        return self._redirect_uri

    def __call__(self, *args: object, **kwargs: object) -> OAuthClient:
        if self._resolve_client is None:
            msg = "OAuthPlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            raise RuntimeError(msg)
        return self._resolve_client(*args, **kwargs)

    def _ensure_dependency_resolver(self, belgie: OAuthBelgieRuntime) -> None:
        if self._resolve_client is not None:
            return

        def resolve_client(
            request: Request,
            response: Response,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> OAuthClient:
            return self.client_type(plugin=self, client=client, request=request, response=response)

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    def normalize_redirect_target(self, target: str | None) -> str | None:
        if not target:
            return None
        parsed = urlparse(target)
        if not parsed.scheme and not parsed.netloc:
            if target.startswith("/") and not target.startswith("//"):
                return target
            return None
        if (parsed.scheme.lower(), parsed.netloc.lower()) != self._base_url_origin:
            return None
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))

    async def resolve_server_metadata(self) -> ProviderMetadata:
        return await self._transport.resolve_server_metadata()

    async def generate_authorization_url(  # noqa: PLR0913
        self,
        state: str,
        *,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
        code_verifier: str | None = None,
        nonce: str | None = None,
    ) -> str:
        return await self._transport.generate_authorization_url(
            state,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
            code_verifier=code_verifier,
            nonce=nonce,
        )

    async def exchange_code_for_tokens(
        self,
        code: str,
        *,
        code_verifier: str | None = None,
    ) -> OAuthTokenSet:
        return await self._transport.exchange_code_for_tokens(code, code_verifier=code_verifier)

    async def start_authorization(  # noqa: PLR0913
        self,
        client: BelgieClient,
        *,
        intent: OAuthFlowIntent,
        individual_id: UUID | None = None,
        redirect_url: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: JSONValue = None,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
        request_sign_up: bool = False,
    ) -> str:
        normalized_redirect = self.normalize_redirect_target(redirect_url)
        normalized_error_redirect = self.normalize_redirect_target(error_redirect_url)
        normalized_new_user_redirect = self.normalize_redirect_target(new_user_redirect_url)
        authorization_url, cookies = await self._flow.start_authorization(
            client,
            intent=intent,
            individual_id=individual_id,
            redirect_url=normalized_redirect,
            error_redirect_url=normalized_error_redirect,
            new_user_redirect_url=normalized_new_user_redirect,
            payload=payload,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
            request_sign_up=request_sign_up,
        )
        start_payload: OAuthStartPayload = {
            "authorization_url": authorization_url,
            "cookies": [cookie.to_dict() for cookie in cookies],
        }
        start_token = self._start_box.encode(
            start_payload,
        )
        return build_provider_start_url(self._base_url, provider_id=self.provider_id, token=start_token)

    async def token_set(  # noqa: PLR0913
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
        auto_refresh: bool = True,
        request: Request | None = None,
        response: Response | None = None,
    ) -> OAuthTokenSet:
        return await self._flow.token_set(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
            request=request,
            response=response,
        )

    async def list_accounts(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
    ) -> list[OAuthLinkedAccount]:
        return await self._flow.list_accounts(client, individual_id=individual_id)

    async def refresh_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
        request: Request | None = None,
        response: Response | None = None,
    ) -> OAuthLinkedAccount:
        return await self._flow.refresh_account(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            request=request,
            response=response,
        )

    async def account_info(  # noqa: PLR0913
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
        auto_refresh: bool = True,
        request: Request | None = None,
        response: Response | None = None,
    ) -> OAuthUserInfo | None:
        return await self._flow.account_info(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
            request=request,
            response=response,
        )

    async def unlink_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str | None = None,
        request: Request | None = None,
        response: Response | None = None,
    ) -> bool:
        return await self._flow.unlink_account(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            request=request,
            response=response,
        )

    def router(self, belgie: OAuthBelgieRuntime) -> APIRouter:  # noqa: C901, PLR0915
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(prefix=f"/provider/{self.provider_id}", tags=["auth", "oauth"])

        @router.get("/start")
        def start(token: Annotated[str, Query()]) -> RedirectResponse:
            payload = self._start_box.decode(token, error_message="invalid OAuth start token")
            authorization_url = coerce_optional_str(payload.get("authorization_url"))
            if authorization_url is None:
                msg = "missing OAuth authorization URL"
                raise OAuthError(msg)
            response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
            if isinstance(cookie_payloads := payload.get("cookies"), list):
                for cookie_payload in cookie_payloads:
                    if not isinstance(cookie_payload, dict):
                        continue
                    cookie = ResponseCookie.from_dict(cookie_payload)
                    response.set_cookie(
                        key=cookie.name,
                        value=cookie.value,
                        max_age=cookie.max_age,
                        path=cookie.path,
                        httponly=cookie.httponly,
                        secure=cookie.secure,
                        samesite=cookie.samesite,
                        domain=cookie.domain,
                    )
            return response

        @router.post("/signin/id-token", response_model=OAuthSessionSignInResponse)
        async def signin_id_token(
            payload: OAuthIdTokenRequest,
            request: Request,
            response: Response,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> OAuthSessionSignInResponse:
            try:
                result = await self._flow.signin_with_id_token(
                    belgie=belgie,
                    client=client,
                    request=request,
                    response=response,
                    id_token=payload.id_token,
                    nonce=payload.nonce,
                    access_token=payload.access_token,
                    refresh_token=payload.refresh_token,
                    token_type=payload.token_type,
                    scope=payload.resolved_scope,
                    access_token_expires_at=payload.access_token_expires_at,
                    refresh_token_expires_at=payload.refresh_token_expires_at,
                    request_sign_up=payload.request_sign_up,
                )
            except OAuthError as exc:
                _raise_oauth_http_error(exc)
            client.create_session_cookie(result.session, response)
            return OAuthSessionSignInResponse.from_session(
                individual=result.individual,
                session=result.session,
            )

        @router.post("/link/id-token", response_model=OAuthStatusResponse)
        async def link_id_token(
            payload: OAuthIdTokenRequest,
            request: Request,
            response: Response,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> OAuthStatusResponse:
            individual = await client.get_individual(SecurityScopes(), request)
            try:
                await self._flow.link_with_id_token(
                    client=client,
                    request=request,
                    response=response,
                    individual_id=individual.id,
                    id_token=payload.id_token,
                    nonce=payload.nonce,
                    access_token=payload.access_token,
                    refresh_token=payload.refresh_token,
                    token_type=payload.token_type,
                    scope=payload.resolved_scope,
                    access_token_expires_at=payload.access_token_expires_at,
                    refresh_token_expires_at=payload.refresh_token_expires_at,
                )
            except OAuthError as exc:
                _raise_oauth_http_error(exc)
            return OAuthStatusResponse(status=True)

        @router.get("/accounts", response_model=OAuthAccountListResponse)
        async def accounts(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> OAuthAccountListResponse:
            individual = await client.get_individual(SecurityScopes(), request)
            accounts = await self.list_accounts(client, individual_id=individual.id)
            return OAuthAccountListResponse(
                accounts=[OAuthAccountResponse.from_account(account) for account in accounts],
            )

        @router.post("/unlink", response_model=OAuthStatusResponse)
        async def unlink(
            payload: OAuthProviderAccountRequest,
            request: Request,
            response: Response,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> OAuthStatusResponse:
            individual = await client.get_individual(SecurityScopes(), request)
            try:
                unlinked = await self.unlink_account(
                    client,
                    individual_id=individual.id,
                    provider_account_id=payload.provider_account_id,
                    request=request,
                    response=response,
                )
            except OAuthError as exc:
                _raise_oauth_http_error(exc)
            return OAuthStatusResponse(status=unlinked)

        @router.post("/access-token", response_model=OAuthTokenResponse)
        async def access_token(
            payload: OAuthProviderAccountRequest,
            request: Request,
            response: Response,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> OAuthTokenResponse:
            individual = await client.get_individual(SecurityScopes(), request)
            try:
                account = await self._flow.linked_account(
                    client,
                    individual_id=individual.id,
                    provider_account_id=payload.provider_account_id,
                    request=request,
                )
                token_set = await self.token_set(
                    client,
                    individual_id=individual.id,
                    provider_account_id=account.provider_account_id,
                    request=request,
                    response=response,
                )
                return OAuthTokenResponse.from_token_set(
                    provider=self.provider_id,
                    provider_account_id=account.provider_account_id,
                    token_set=token_set,
                )
            except (OAuthError, ValueError) as exc:
                if isinstance(exc, OAuthError):
                    _raise_oauth_http_error(exc)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        @router.post("/refresh-token", response_model=OAuthRefreshTokenResponse)
        async def refresh_token(
            payload: OAuthProviderAccountRequest,
            request: Request,
            response: Response,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> OAuthRefreshTokenResponse:
            individual = await client.get_individual(SecurityScopes(), request)
            try:
                account = await self.refresh_account(
                    client,
                    individual_id=individual.id,
                    provider_account_id=payload.provider_account_id,
                    request=request,
                    response=response,
                )
                return OAuthRefreshTokenResponse.from_account(account)
            except (OAuthError, ValueError) as exc:
                if isinstance(exc, OAuthError):
                    _raise_oauth_http_error(exc)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        @router.get("/account-info", response_model=OAuthAccountInfoResponse)
        async def account_info(
            request: Request,
            response: Response,
            provider_account_id: Annotated[str | None, Query()] = None,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> OAuthAccountInfoResponse:
            individual = await client.get_individual(SecurityScopes(), request)
            try:
                account = await self._flow.linked_account(
                    client,
                    individual_id=individual.id,
                    provider_account_id=provider_account_id,
                    request=request,
                )
                user_info = _require_account_info(
                    await self.account_info(
                        client,
                        individual_id=individual.id,
                        provider_account_id=account.provider_account_id,
                        request=request,
                        response=response,
                    ),
                )
                return OAuthAccountInfoResponse(
                    provider=self.provider_id,
                    provider_account_id=account.provider_account_id,
                    user=OAuthUserInfoResponse.from_user_info(user_info),
                )
            except OAuthError as exc:
                _raise_oauth_http_error(exc)

        async def complete_callback(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> RedirectResponse:
            return await self._flow.complete_callback(
                belgie=belgie,
                client=client,
                request=request,
            )

        @router.get("/callback")
        async def callback_get(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            return await complete_callback(request, client)

        @router.post("/callback")
        async def callback_post(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008, FAST002
        ) -> RedirectResponse:
            return await complete_callback(request, client)

        return router

    def public(self, belgie: OAuthBelgieRuntime) -> APIRouter:  # noqa: ARG002
        return APIRouter()


__all__ = [
    "ConsumedOAuthState",
    "OAuthClient",
    "OAuthLinkedAccount",
    "OAuthPlugin",
    "OAuthProvider",
    "OAuthSettings",
    "OAuthTokenSet",
    "OAuthUserInfo",
]
