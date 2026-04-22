from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from belgie_core.core.client import BelgieClient
from belgie_core.core.exceptions import OAuthError
from belgie_core.core.plugin import PluginClient
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse

from belgie_oauth._config import OAuthProvider
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
    JSONValue,
    OAuthLinkedAccount,
    OAuthResponseMode,
    OAuthTokenSet,
    OAuthUserInfo,
    ResponseCookie,
)
from belgie_oauth._state import build_state_store
from belgie_oauth._transport import OAuthTransport

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings


@dataclass(slots=True, kw_only=True)
class OAuthClient:
    plugin: OAuthPlugin
    client: BelgieClient

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
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthTokenSet:
        return await self.plugin.token_set(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
        )

    async def get_access_token(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> str:
        token_set = await self.token_set(
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
        )
        return token_set.access_token

    async def refresh_account(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> OAuthLinkedAccount:
        return await self.plugin.refresh_account(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )

    async def account_info(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthUserInfo | None:
        return await self.plugin.account_info(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
        )

    async def unlink_account(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> bool:
        return await self.plugin.unlink_account(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )


class OAuthPlugin(PluginClient):
    def __init__(
        self,
        belgie_settings: BelgieSettings,
        config: OAuthProvider,
        *,
        client_type: type[OAuthClient] = OAuthClient,
    ) -> None:
        self.config = config
        self._client_type = client_type
        self._redirect_uri = build_provider_callback_url(
            belgie_settings.base_url,
            provider_id=self.provider_id,
        )
        self._resolve_client: Any = None
        self._base_url = belgie_settings.base_url
        parsed_base_url = urlparse(belgie_settings.base_url)
        self._base_url_origin = (parsed_base_url.scheme.lower(), parsed_base_url.netloc.lower())
        self._start_box = SecretBox(secret=belgie_settings.secret, label="oauth redirect start")
        encryption_secret = (
            config.token_encryption_secret.get_secret_value()
            if config.token_encryption_secret is not None
            else belgie_settings.secret
        )
        self._transport = OAuthTransport(config, redirect_uri=self.redirect_uri)
        self._state_store = build_state_store(
            provider_id=self.provider_id,
            strategy=config.state_strategy,
            cookie_settings=belgie_settings.cookie,
            secret=belgie_settings.secret,
        )
        self._flow = OAuthFlowCoordinator(
            config=config,
            provider_id=self.provider_id,
            transport=self._transport,
            state_store=self._state_store,
            token_codec=OAuthTokenCodec(enabled=config.encrypt_tokens, secret=encryption_secret),
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

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        type BelgieClientDep = BelgieClient

        def resolve_client(client: BelgieClientDep = Depends(belgie)) -> OAuthClient:  # noqa: B008
            return self._client_type(plugin=self, client=client)

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

    async def resolve_server_metadata(self) -> dict[str, Any]:
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
        intent: str,
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
        start_token = self._start_box.encode(
            {
                "authorization_url": authorization_url,
                "cookies": cookies,
            },
        )
        return build_provider_start_url(self._base_url, provider_id=self.provider_id, token=start_token)

    async def token_set(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthTokenSet:
        return await self._flow.token_set(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
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
        provider_account_id: str,
    ) -> OAuthLinkedAccount:
        return await self._flow.refresh_account(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )

    async def account_info(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthUserInfo | None:
        return await self._flow.account_info(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
        )

    async def unlink_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> bool:
        return await self._flow.unlink_account(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )

    def router(self, belgie: Belgie) -> APIRouter:
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(prefix=f"/provider/{self.provider_id}", tags=["auth", "oauth"])

        @router.get("/start")
        async def start(token: str) -> RedirectResponse:
            payload = self._start_box.decode(token, error_message="invalid OAuth start token")
            authorization_url = coerce_optional_str(payload.get("authorization_url"))
            if authorization_url is None:
                msg = "missing OAuth authorization URL"
                raise OAuthError(msg)
            response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
            for cookie_payload in payload.get("cookies", []):
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

        @router.api_route("/callback", methods=["GET", "POST"])
        async def callback(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> RedirectResponse:
            return await self._flow.complete_callback(
                belgie=belgie,
                client=client,
                request=request,
            )

        return router

    def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return APIRouter()


__all__ = [
    "ConsumedOAuthState",
    "OAuthClient",
    "OAuthLinkedAccount",
    "OAuthPlugin",
    "OAuthProvider",
    "OAuthTokenSet",
    "OAuthUserInfo",
]
