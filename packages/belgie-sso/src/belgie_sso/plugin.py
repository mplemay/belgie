# ruff: noqa: ARG001, C901, EM101, FAST002, FBT002, PLR0913, PLR0915, TRY003, TRY300

from __future__ import annotations

import html
import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlparse, urlunparse
from uuid import NAMESPACE_URL, UUID, uuid5

from belgie_core.core.client import BelgieClient  # noqa: TC002
from belgie_core.core.exceptions import OAuthError
from belgie_core.core.plugin import AfterAuthenticateHook, AuthenticatedProfile, PluginClient
from belgie_core.utils.crypto import generate_state_token
from belgie_oauth._config import OAuthProvider
from belgie_oauth._errors import OAuthCallbackError
from belgie_oauth._helpers import append_query_params, generate_code_verifier
from belgie_oauth._models import ConsumedOAuthState, OAuthTokenSet, OAuthUserInfo, PendingOAuthState, ResponseCookie
from belgie_oauth._state import AdapterOAuthStateStore
from belgie_organization.plugin import OrganizationPlugin
from belgie_proto.sso import OIDCProviderConfig, SAMLProviderConfig, SSODomainProtocol, SSOProviderProtocol
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import SecurityScopes
from pydantic import SecretStr

from belgie_sso.client import SSOClient
from belgie_sso.discovery import DiscoveryError, ValidatingOAuthTransport, needs_runtime_discovery
from belgie_sso.models import SSOProvisioningContext
from belgie_sso.org_assignment import (
    assign_individual_by_domain,
    assign_individual_to_provider_organization,
    provider_matches_domain,
)
from belgie_sso.saml import BuiltinSAMLEngine, SAMLLogoutEngine, SAMLLogoutResult, SAMLStartResult
from belgie_sso.utils import (
    as_account_provider,
    build_provider_callback_url,
    build_shared_callback_url,
    choose_best_domain_match,
    choose_best_verified_domain_match,
    deserialize_oidc_config,
    deserialize_saml_config,
    extract_email_domain,
    normalize_domain,
    normalize_provider_id,
    normalize_redirect_target,
    parse_bool_claim,
    serialize_oidc_config,
    serialize_saml_config,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_oauth._transport import OAuthTransport
    from belgie_proto.core.individual import IndividualProtocol
    from belgie_proto.sso.provider import OIDCConfigValue, SAMLConfigValue

    from belgie_sso.settings import EnterpriseSSO

logger = logging.getLogger(__name__)


@dataclass(slots=True, kw_only=True)
class TokenResponse:
    access_token: str
    token_type: str | None
    refresh_token: str | None
    scope: str | None
    id_token: str | None
    expires_at: datetime | None


@dataclass(slots=True, kw_only=True, frozen=True)
class _DefaultProvider:
    id: UUID
    organization_id: UUID | None
    created_by_individual_id: UUID | None
    provider_type: str
    provider_id: str
    issuer: str
    oidc_config: dict[str, OIDCConfigValue] | None
    saml_config: dict[str, SAMLConfigValue] | None
    created_at: datetime
    updated_at: datetime
    domain: str


class SSOPlugin[
    ProviderT: SSOProviderProtocol,
    DomainT: SSODomainProtocol,
](PluginClient, AfterAuthenticateHook):
    def __init__(
        self,
        belgie_settings: BelgieSettings,
        settings: EnterpriseSSO[ProviderT, DomainT],
    ) -> None:
        self._belgie_settings = belgie_settings
        self._settings = settings
        self._state_store = AdapterOAuthStateStore(
            provider_id="sso",
            cookie_settings=belgie_settings.cookie,
            secret=belgie_settings.secret,
        )
        self._saml_engine = settings.saml_engine or BuiltinSAMLEngine(settings=settings.saml)
        self._resolve_client: Callable[..., Awaitable[SSOClient]] | None = None
        self._organization_plugin: OrganizationPlugin | None = None
        self._organization_plugin_resolved = False

    @property
    def settings(self) -> EnterpriseSSO[ProviderT, DomainT]:
        return self._settings

    def _resolve_organization_plugin(self, belgie: Belgie) -> OrganizationPlugin | None:
        if self._organization_plugin_resolved:
            return self._organization_plugin

        self._organization_plugin_resolved = True
        self._organization_plugin = next(
            (plugin for plugin in belgie.plugins if isinstance(plugin, OrganizationPlugin)),
            None,
        )
        return self._organization_plugin

    def _organization_adapter(
        self,
        belgie: Belgie,
    ) -> object | None:
        organization_plugin = self._resolve_organization_plugin(belgie)
        if organization_plugin is None:
            return None
        return organization_plugin.settings.adapter

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        async def resolve_client(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> SSOClient:
            current_individual = await client.get_individual(SecurityScopes(), request)
            return SSOClient(
                client=client,
                settings=self._settings,
                organization_adapter=self._organization_adapter(belgie),
                current_individual=current_individual,
            )

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    async def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> SSOClient:
        if self._resolve_client is None:
            msg = "SSOPlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    async def after_authenticate(
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,  # noqa: ARG002
        individual: IndividualProtocol[str],
        profile: AuthenticatedProfile,
    ) -> None:
        if not profile.email_verified or not profile.email:
            return

        await assign_individual_by_domain(
            db=client.db,
            adapter=self._settings.adapter,
            organization_adapter=self._organization_adapter(belgie),
            individual=individual,
            email=profile.email,
            verified_only=self._settings.domain_verification.enabled,
            role=self._settings.organization_default_role,
        )

    def router(self, belgie: Belgie) -> APIRouter:
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(prefix="/provider/sso", tags=["auth", "sso"])

        @router.get("/signin")
        async def signin(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
            provider_id: Annotated[str | None, Query()] = None,
            email: Annotated[str | None, Query()] = None,
            domain: Annotated[str | None, Query()] = None,
            organization_slug: Annotated[str | None, Query()] = None,
            redirect_to: Annotated[str | None, Query()] = None,
            error_redirect_url: Annotated[str | None, Query()] = None,
            new_user_redirect_url: Annotated[str | None, Query()] = None,
            request_sign_up: Annotated[bool, Query()] = False,
            login_hint: Annotated[str | None, Query()] = None,
            scopes: Annotated[list[str] | None, Query()] = None,
        ) -> Response:
            provider = await self._resolve_provider_for_signin(
                belgie=belgie,
                client=client,
                provider_id=provider_id,
                email=email,
                domain=domain,
                organization_slug=organization_slug,
            )
            if provider.provider_type == "saml":
                return await self._start_saml_signin(
                    provider=provider,
                    client=client,
                    redirect_to=redirect_to,
                    error_redirect_url=error_redirect_url,
                    new_user_redirect_url=new_user_redirect_url,
                    request_sign_up=request_sign_up,
                )
            return await self._start_oidc_signin(
                provider=provider,
                client=client,
                email=email,
                login_hint=login_hint,
                redirect_to=redirect_to,
                error_redirect_url=error_redirect_url,
                new_user_redirect_url=new_user_redirect_url,
                request_sign_up=request_sign_up,
                scopes=scopes,
            )

        async def complete_callback(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
            provider_id: str | None = None,
        ) -> Response:
            callback_params = await self._extract_callback_params(request)
            if callback_params.get("SAMLResponse") is not None or callback_params.get("RelayState") is not None:
                return await self._complete_saml_callback(
                    belgie=belgie,
                    client=client,
                    request=request,
                    provider_id=provider_id,
                )
            return await self._complete_oidc_callback(
                belgie=belgie,
                client=client,
                request=request,
                provider_id=provider_id,
            )

        @router.get("/callback")
        async def callback_get(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await complete_callback(request, client)

        @router.post("/callback")
        async def callback_post(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await complete_callback(request, client)

        @router.get("/callback/{provider_id}")
        async def callback_with_provider_get(
            provider_id: Annotated[str, Path(min_length=1)],
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await complete_callback(request, client, provider_id)

        @router.post("/callback/{provider_id}")
        async def callback_with_provider_post(
            provider_id: Annotated[str, Path(min_length=1)],
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await complete_callback(request, client, provider_id)

        @router.get("/acs/{provider_id}")
        async def acs_get(
            provider_id: Annotated[str, Path(min_length=1)],
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await complete_callback(request, client, provider_id)

        @router.post("/acs/{provider_id}")
        async def acs_post(
            provider_id: Annotated[str, Path(min_length=1)],
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await complete_callback(request, client, provider_id)

        @router.get("/signout")
        async def saml_signout(
            provider_id: Annotated[str, Query(min_length=1)],
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
            redirect_to: Annotated[str | None, Query()] = None,
        ) -> Response:
            return await self._start_saml_logout(
                belgie=belgie,
                client=client,
                request=request,
                provider_id=provider_id,
                redirect_to=redirect_to,
            )

        @router.get("/slo/{provider_id}")
        async def slo_get(
            provider_id: Annotated[str, Path(min_length=1)],
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await self._complete_saml_logout(
                belgie=belgie,
                client=client,
                request=request,
                provider_id=provider_id,
            )

        @router.post("/slo/{provider_id}")
        async def slo_post(
            provider_id: Annotated[str, Path(min_length=1)],
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> Response:
            return await self._complete_saml_logout(
                belgie=belgie,
                client=client,
                request=request,
                provider_id=provider_id,
            )

        @router.get("/metadata/{provider_id}")
        async def metadata(
            provider_id: Annotated[str, Path(min_length=1)],
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> HTMLResponse:
            provider = await self._get_provider_by_provider_id(client=client, provider_id=provider_id)
            if provider.provider_type != "saml":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="provider metadata is only available for saml providers",
                )

            try:
                metadata_xml = await self._saml_engine.metadata_xml(
                    provider=provider,
                    config=self._provider_saml_config(provider),
                    acs_url=self._saml_callback_url(provider.provider_id),
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            return HTMLResponse(content=metadata_xml, media_type="application/xml")

        return router

    def public(self, belgie: Belgie) -> APIRouter | None:  # noqa: ARG002
        return None

    async def _start_oidc_signin(
        self,
        *,
        provider: ProviderT,
        client: BelgieClient,
        email: str | None,
        login_hint: str | None,
        redirect_to: str | None,
        error_redirect_url: str | None,
        new_user_redirect_url: str | None,
        request_sign_up: bool,
        scopes: list[str] | None,
    ) -> RedirectResponse:
        await self._ensure_provider_verified_or_http(client=client, provider=provider)
        transport = self._build_oidc_transport(provider)
        normalized_redirect = self._normalize_redirect_target(redirect_to)
        normalized_error_redirect = self._normalize_redirect_target(error_redirect_url)
        normalized_new_user_redirect = self._normalize_redirect_target(new_user_redirect_url)
        state = generate_state_token()
        code_verifier = generate_code_verifier() if transport.config.use_pkce else None
        nonce = generate_state_token() if transport.should_use_nonce(scopes) else None
        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.state_ttl_seconds)
        try:
            authorization_url = await transport.generate_authorization_url(
                state,
                scopes=scopes,
                authorization_params={"login_hint": login_hint.strip()}
                if login_hint
                else {"login_hint": email.lower()}
                if email
                else None,
                code_verifier=code_verifier,
                nonce=nonce,
            )
        except DiscoveryError as exc:
            if target := normalized_error_redirect or normalized_redirect:
                return self._error_redirect_response(
                    exc=OAuthCallbackError("discovery_failed", str(exc)),
                    target=target,
                )
            self._raise_discovery_http_exception(exc)
        cookies = await self._state_store.create_authorization_state(
            client,
            PendingOAuthState(
                state=state,
                provider="sso",
                individual_id=None,
                code_verifier=code_verifier,
                nonce=nonce,
                intent="signin",
                redirect_url=normalized_redirect,
                error_redirect_url=normalized_error_redirect,
                new_user_redirect_url=normalized_new_user_redirect,
                payload={
                    "provider_id": provider.provider_id,
                    "flow": "oidc",
                },
                request_sign_up=request_sign_up,
                expires_at=expires_at,
            ),
        )
        response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
        self._apply_response_cookies(response, cookies)
        return response

    async def _complete_oidc_callback(  # noqa: PLR0912
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        provider_id: str | None,
    ) -> RedirectResponse:
        consumed_state: ConsumedOAuthState | None = None
        try:
            if normalization := await self._normalize_form_post_callback(request):
                return normalization

            callback_params = await self._extract_callback_params(request)
            if not (state := callback_params.get("state")):
                raise OAuthCallbackError("state_mismatch", "missing OAuth state")

            consumed_state = await self._state_store.consume_callback_state(client, request, state)
            resolved_provider_id = self._payload_provider_id(consumed_state)
            if provider_id is not None and self._normalize_provider_id_or_400(provider_id) != resolved_provider_id:
                raise OAuthCallbackError("state_mismatch", "OAuth state provider mismatch")

            provider = await self._get_provider_by_provider_id(client=client, provider_id=resolved_provider_id)
            if provider.provider_type != "oidc":
                raise OAuthCallbackError("state_mismatch", "OAuth state provider mismatch")
            await self._ensure_provider_verified_or_oauth_error(client=client, provider=provider)

            transport = self._build_oidc_transport(provider)
            try:
                metadata = await transport.resolve_server_metadata()
            except DiscoveryError as exc:
                raise OAuthCallbackError("discovery_failed", str(exc)) from exc
            try:
                transport.validate_issuer_parameter(callback_params.get("iss"), metadata)
            except ValueError as exc:
                raise OAuthCallbackError("issuer_mismatch", str(exc)) from exc

            request.state.oauth_state = consumed_state
            request.state.oauth_payload = consumed_state.payload

            if callback_params.get("error"):
                description = callback_params.get("error_description") or callback_params["error"]
                raise OAuthCallbackError(str(callback_params["error"]), description)
            if not (code := callback_params.get("code")):
                raise OAuthCallbackError("oauth_code_verification_failed", "missing OAuth authorization code")

            try:
                token_set = await transport.exchange_code_for_tokens(
                    code,
                    code_verifier=consumed_state.code_verifier,
                )
                provider_user = await transport.fetch_provider_profile(
                    token_set,
                    nonce=consumed_state.nonce,
                )
            except DiscoveryError as exc:
                raise OAuthCallbackError("discovery_failed", str(exc)) from exc
            except OAuthError as exc:
                if isinstance(exc, OAuthCallbackError):
                    raise
                raise OAuthCallbackError("oauth_code_verification_failed", str(exc)) from exc

            response = await self._complete_signin_flow(
                belgie=belgie,
                client=client,
                request=request,
                provider=provider,
                oauth_state=consumed_state,
                provider_user=provider_user,
                token_set=token_set,
            )
            self._state_store.clear_cookies(response)
            return response
        except OAuthError as exc:
            if consumed_state and (target := self._error_redirect_target(consumed_state)):
                response = self._error_redirect_response(exc=exc, target=target)
                self._state_store.clear_cookies(response)
                return response
            raise

    async def _start_saml_signin(
        self,
        *,
        provider: ProviderT,
        client: BelgieClient,
        redirect_to: str | None,
        error_redirect_url: str | None,
        new_user_redirect_url: str | None,
        request_sign_up: bool,
    ) -> Response:
        await self._ensure_provider_verified_or_http(client=client, provider=provider)
        state = generate_state_token()
        try:
            start_result = await self._saml_engine.start_signin(
                provider=provider,
                config=self._provider_saml_config(provider),
                acs_url=self._saml_callback_url(provider.provider_id),
                relay_state=state,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        payload: dict[str, str] = {
            "provider_id": provider.provider_id,
            "flow": "saml",
        }
        if start_result.request_id is not None:
            payload["request_id"] = start_result.request_id
        await client.adapter.create_oauth_state(
            client.db,
            state=state,
            expires_at=(datetime.now(UTC) + timedelta(seconds=self._settings.state_ttl_seconds)).replace(tzinfo=None),
            provider="sso",
            redirect_url=self._normalize_redirect_target(redirect_to),
            error_redirect_url=self._normalize_redirect_target(error_redirect_url),
            new_user_redirect_url=self._normalize_redirect_target(new_user_redirect_url),
            payload=payload,
            request_sign_up=request_sign_up,
        )

        if start_result.redirect_url is not None:
            return RedirectResponse(url=start_result.redirect_url, status_code=status.HTTP_302_FOUND)
        if start_result.form_action is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SAML provider did not return a usable sign-in response",
            )
        return self._render_saml_form(start_result)

    async def _complete_saml_callback(
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        provider_id: str | None,
    ) -> RedirectResponse:
        consumed_state: ConsumedOAuthState | None = None
        try:
            callback_params = await self._extract_callback_params(request)
            relay_state = callback_params.get("RelayState")
            if (
                relay_state
                and (oauth_state := await client.adapter.get_oauth_state(client.db, relay_state)) is not None
            ):
                await client.adapter.delete_oauth_state(client.db, relay_state)
                consumed_state = ConsumedOAuthState.from_model(oauth_state)
                resolved_provider_id = self._payload_provider_id(consumed_state)
                if provider_id is not None and self._normalize_provider_id_or_400(provider_id) != resolved_provider_id:
                    raise OAuthCallbackError("state_mismatch", "SAML state provider mismatch")
                provider = await self._get_provider_by_provider_id(client=client, provider_id=resolved_provider_id)
            else:
                if provider_id is None:
                    raise OAuthCallbackError("state_mismatch", "missing SAML RelayState")
                provider = await self._get_provider_by_provider_id(client=client, provider_id=provider_id)
                if provider.provider_type != "saml":
                    raise OAuthCallbackError("state_mismatch", "SAML state provider mismatch")
                if not self._provider_saml_config(provider).allow_idp_initiated:
                    raise OAuthCallbackError("state_mismatch", "missing SAML RelayState")
                consumed_state = ConsumedOAuthState(
                    state=relay_state or generate_state_token(),
                    provider="sso",
                    individual_id=None,
                    code_verifier=None,
                    nonce=None,
                    intent="signin",
                    redirect_url=self._normalize_redirect_target(relay_state),
                    error_redirect_url=None,
                    new_user_redirect_url=None,
                    payload={"provider_id": provider.provider_id, "flow": "saml"},
                    request_sign_up=False,
                    expires_at=datetime.now(UTC) + timedelta(seconds=self._settings.state_ttl_seconds),
                )

            if provider.provider_type != "saml":
                raise OAuthCallbackError("state_mismatch", "SAML state provider mismatch")
            await self._ensure_provider_verified_or_oauth_error(client=client, provider=provider)

            request.state.oauth_state = consumed_state
            request.state.oauth_payload = consumed_state.payload

            try:
                saml_profile = await self._saml_engine.finish_signin(
                    provider=provider,
                    config=self._provider_saml_config(provider),
                    request=request,
                    relay_state=relay_state or "",
                    request_id=self._payload_request_id(consumed_state),
                )
            except RuntimeError as exc:
                raise OAuthError(str(exc)) from exc
            await self._record_saml_assertion(client=client, provider=provider, saml_profile=saml_profile)

            return await self._complete_signin_flow(
                belgie=belgie,
                client=client,
                request=request,
                provider=provider,
                oauth_state=consumed_state,
                provider_user=OAuthUserInfo(
                    provider_account_id=saml_profile.provider_account_id,
                    email=saml_profile.email.lower() if saml_profile.email else None,
                    email_verified=saml_profile.email_verified,
                    name=saml_profile.name,
                    raw={
                        **dict(saml_profile.raw),
                        "session_index": saml_profile.session_index,
                        "assertion_id": saml_profile.assertion_id,
                        "in_response_to": saml_profile.in_response_to,
                    },
                ),
                token_set=None,
            )
        except OAuthError as exc:
            if consumed_state and (target := self._error_redirect_target(consumed_state)):
                return self._error_redirect_response(exc=exc, target=target)
            raise

    async def _start_saml_logout(
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        provider_id: str,
        redirect_to: str | None,
    ) -> Response:
        provider = await self._get_provider_by_provider_id(client=client, provider_id=provider_id)
        if provider.provider_type != "saml":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="single logout is only available for saml providers",
            )
        if not isinstance(self._saml_engine, SAMLLogoutEngine):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SAML single logout is not configured",
            )
        session = await client.get_session(request)
        saml_session = await client.adapter.get_oauth_state(client.db, self._saml_session_state_key(session.id))
        if saml_session is None or not isinstance(saml_session.payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current session is not linked to a SAML provider session",
            )
        if saml_session.payload.get("provider_id") != provider.provider_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current session is not linked to the requested SAML provider",
            )
        provider_account_id = saml_session.payload.get("provider_account_id")
        if not isinstance(provider_account_id, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current SAML session is missing a logout subject",
            )
        normalized_redirect = self._normalize_redirect_target(redirect_to) or belgie.settings.urls.signout_redirect
        try:
            logout_result = await self._saml_engine.start_logout(
                provider=provider,
                config=self._provider_saml_config(provider),
                slo_url=self._saml_slo_url(provider.provider_id),
                relay_state=normalized_redirect,
                provider_account_id=provider_account_id,
                session_index=(
                    saml_session.payload.get("session_index")
                    if isinstance(saml_session.payload.get("session_index"), str)
                    else None
                ),
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        if logout_result.request_id is not None:
            await self._replace_oauth_state(
                client=client,
                state=self._saml_logout_request_state_key(logout_result.request_id),
                expires_at=datetime.now(UTC) + timedelta(seconds=self._settings.saml.logout_request_ttl_seconds),
                payload={
                    "kind": "saml_logout_request",
                    "provider_id": provider.provider_id,
                    "session_id": str(session.id),
                    "redirect_url": normalized_redirect,
                },
            )
        return self._response_from_saml_result(logout_result)

    async def _complete_saml_logout(
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        provider_id: str,
    ) -> Response:
        provider = await self._get_provider_by_provider_id(client=client, provider_id=provider_id)
        if provider.provider_type != "saml":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="single logout is only available for saml providers",
            )
        if not isinstance(self._saml_engine, SAMLLogoutEngine):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SAML single logout is not configured",
            )
        try:
            logout_profile = await self._saml_engine.finish_logout(
                provider=provider,
                config=self._provider_saml_config(provider),
                request=request,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        if logout_profile.flow == "request":
            session_id = await self._resolve_saml_logout_session_id(
                client=client,
                provider=provider,
                logout_profile=logout_profile,
            )
            if session_id is not None:
                await belgie.sign_out(client.db, session_id)
                await self._delete_saml_session_state(client=client, session_id=session_id)
            logout_result = await self._saml_engine.build_logout_response(
                provider=provider,
                config=self._provider_saml_config(provider),
                slo_url=self._saml_slo_url(provider.provider_id),
                relay_state=logout_profile.relay_state,
                in_response_to=logout_profile.request_id,
            )
            response = self._response_from_saml_result(logout_result)
            if session_id is not None:
                self._clear_session_cookie(response)
            return response

        redirect_url = belgie.settings.urls.signout_redirect
        if (
            logout_profile.in_response_to is not None
            and (
                oauth_state := await client.adapter.get_oauth_state(
                    client.db,
                    self._saml_logout_request_state_key(logout_profile.in_response_to),
                )
            )
            is not None
        ):
            if isinstance(oauth_state.payload, dict) and isinstance(oauth_state.payload.get("redirect_url"), str):
                redirect_url = oauth_state.payload["redirect_url"]
            session_id = self._payload_session_id(oauth_state)
            await client.adapter.delete_oauth_state(
                client.db,
                self._saml_logout_request_state_key(logout_profile.in_response_to),
            )
            if session_id is not None:
                await belgie.sign_out(client.db, session_id)
                await self._delete_saml_session_state(client=client, session_id=session_id)
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        self._clear_session_cookie(response)
        return response

    async def _complete_signin_flow(  # noqa: PLR0912
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        provider: ProviderT,
        oauth_state: ConsumedOAuthState,
        provider_user: OAuthUserInfo,
        token_set: OAuthTokenSet | None,
    ) -> RedirectResponse:
        account_provider = as_account_provider(provider.provider_id)
        existing_account = await client.get_oauth_account(
            provider=account_provider,
            provider_account_id=provider_user.provider_account_id,
        )

        if existing_account is not None:
            individual = await client.adapter.get_individual_by_id(client.db, existing_account.individual_id)
            if individual is None:
                raise OAuthError("linked individual not found")
            individual = (
                await self._refresh_individual_profile(client, provider, individual, provider_user) or individual
            )
            session = await client.sign_in_individual(individual, request=request)
            if token_set is not None:
                updated_account = await client.update_oauth_account_by_id(
                    existing_account.id,
                    **self._token_updates(token_set),
                )
                if updated_account is None:
                    raise OAuthError("failed to update linked oauth account")

            await self._run_provision_user(
                individual=individual,
                provider=provider,
                provider_user=provider_user,
                token_set=token_set,
                created=False,
            )
            await self._assign_provider_organization(
                belgie=belgie,
                provider=provider,
                individual=individual,
                provider_user=provider_user,
                token_set=token_set,
                created=False,
                db=client.db,
            )
            await belgie.after_authenticate(
                client=client,
                request=request,
                individual=individual,
                profile=AuthenticatedProfile(
                    provider=account_provider,
                    provider_account_id=provider_user.provider_account_id,
                    email=provider_user.email or individual.email,
                    email_verified=provider_user.email_verified,
                    name=provider_user.name,
                    image=provider_user.image,
                ),
            )
            await self._store_saml_session_state(
                client=client,
                provider=provider,
                session=session,
                provider_user=provider_user,
            )
            response = RedirectResponse(
                url=oauth_state.redirect_url or belgie.settings.urls.signin_redirect,
                status_code=status.HTTP_302_FOUND,
            )
            return client.create_session_cookie(session, response)

        if provider_user.email is None:
            raise OAuthCallbackError("email_missing", "provider user info missing email")

        email = provider_user.email.lower()
        existing_individual = await client.adapter.get_individual_by_email(client.db, email)
        trusted_email = await self._is_trusted_email(
            client=client,
            provider=provider,
            email=email,
            email_verified=provider_user.email_verified,
        )
        if existing_individual is not None:
            if not trusted_email:
                raise OAuthCallbackError(
                    "account_not_linked",
                    "provider email is not trusted for implicit account linking",
                )
        else:
            if self._settings.disable_sign_up or (
                self._settings.disable_implicit_sign_up and not oauth_state.request_sign_up
            ):
                raise OAuthCallbackError("signup_disabled", "sign up is disabled for this provider")
            if not trusted_email:
                raise OAuthCallbackError("signup_disabled", "email domain is not verified for this provider")

        verified_at = datetime.now(UTC) if provider_user.email_verified else None
        individual, created = await client.get_or_create_individual(
            email,
            name=provider_user.name,
            image=provider_user.image,
            email_verified_at=verified_at,
        )
        if not created:
            if not trusted_email:
                raise OAuthCallbackError(
                    "account_not_linked",
                    "provider email is not trusted for implicit account linking",
                )
            individual = (
                await self._refresh_individual_profile(client, provider, individual, provider_user) or individual
            )

        session = await client.sign_in_individual(individual, request=request)
        if created and client.after_sign_up is not None:
            await client.after_sign_up(client=client, request=request, individual=individual)

        try:
            await client.upsert_oauth_account(
                individual_id=individual.id,
                provider=account_provider,
                provider_account_id=provider_user.provider_account_id,
                **self._token_updates(token_set),
            )
        except OAuthError as exc:
            if "already linked to another individual" in str(exc):
                raise OAuthCallbackError("account_already_linked_to_different_user", str(exc)) from exc
            raise

        await self._run_provision_user(
            individual=individual,
            provider=provider,
            provider_user=provider_user,
            token_set=token_set,
            created=created,
        )
        await self._assign_provider_organization(
            belgie=belgie,
            provider=provider,
            individual=individual,
            provider_user=provider_user,
            token_set=token_set,
            created=created,
            db=client.db,
        )
        await belgie.after_authenticate(
            client=client,
            request=request,
            individual=individual,
            profile=AuthenticatedProfile(
                provider=account_provider,
                provider_account_id=provider_user.provider_account_id,
                email=email,
                email_verified=provider_user.email_verified,
                name=provider_user.name,
                image=provider_user.image,
            ),
        )
        await self._store_saml_session_state(
            client=client,
            provider=provider,
            session=session,
            provider_user=provider_user,
        )

        redirect_url = belgie.settings.urls.signin_redirect
        if created and oauth_state.new_user_redirect_url:
            redirect_url = oauth_state.new_user_redirect_url
        elif oauth_state.redirect_url:
            redirect_url = oauth_state.redirect_url

        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        return client.create_session_cookie(session, response)

    async def _resolve_provider_for_signin(  # noqa: PLR0912
        self,
        *,
        belgie: Belgie,
        client: BelgieClient,
        provider_id: str | None,
        email: str | None,
        domain: str | None,
        organization_slug: str | None,
    ) -> ProviderT:
        if provider_id:
            return await self._get_provider_by_provider_id(client=client, provider_id=provider_id)

        if organization_slug:
            organization_adapter = self._organization_adapter(belgie)
            if organization_adapter is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization support is not enabled",
                )
            organization = await organization_adapter.get_organization_by_slug(client.db, organization_slug.strip())
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="organization not found",
                )
            providers = await self._settings.adapter.list_providers_for_organization(
                client.db,
                organization_id=organization.id,
            )
            if not providers:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="organization has no sso providers",
                )
            if len(providers) > 1 and (default_provider := self._default_provider(providers)) is not None:
                return default_provider
            if len(providers) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="organization has multiple sso providers",
                )
            return providers[0]

        resolved_domain = domain
        if resolved_domain is None and email is not None:
            resolved_domain = extract_email_domain(email)
        if resolved_domain is None:
            if self._settings.default_sso is not None:
                return await self._get_db_provider_by_provider_id(client=client, provider_id=self._settings.default_sso)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_id, email, domain, or organization_slug is required",
            )
        try:
            resolved_domain = normalize_domain(resolved_domain)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        if default_provider := self._default_provider_for_domain(resolved_domain):
            return default_provider

        try:
            matched_domain = (
                choose_best_verified_domain_match(
                    domain=resolved_domain,
                    domains=await self._settings.adapter.list_verified_domains_matching(
                        client.db,
                        domain=resolved_domain,
                    ),
                )
                if self._settings.domain_verification.enabled
                else choose_best_domain_match(
                    domain=resolved_domain,
                    domains=await self._settings.adapter.list_domains_matching(
                        client.db,
                        domain=resolved_domain,
                    ),
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        if matched_domain is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "no verified provider found for domain"
                    if self._settings.domain_verification.enabled
                    else "no provider found for domain"
                ),
            )

        provider = await self._settings.adapter.get_provider_by_id(
            client.db,
            sso_provider_id=matched_domain.sso_provider_id,
        )
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
        return provider

    async def _get_provider_by_provider_id(
        self,
        *,
        client: BelgieClient,
        provider_id: str,
    ) -> ProviderT | _DefaultProvider:
        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        if default_provider := self._default_provider_for_provider_id(normalized_provider_id):
            return default_provider
        return await self._get_db_provider_by_provider_id(client=client, provider_id=normalized_provider_id)

    async def _get_db_provider_by_provider_id(self, *, client: BelgieClient, provider_id: str) -> ProviderT:
        normalized_provider_id = self._normalize_provider_id_or_400(provider_id)
        provider = await self._settings.adapter.get_provider_by_provider_id(
            client.db,
            provider_id=normalized_provider_id,
        )
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
        return provider

    def _build_oidc_transport(self, provider: ProviderT) -> OAuthTransport:
        config = self._provider_oidc_config(provider)
        discovery_url = config.discovery_endpoint
        if discovery_url is None and needs_runtime_discovery(config):
            discovery_url = f"{config.issuer}/.well-known/openid-configuration"

        oauth_provider = OAuthProvider(
            provider_id="sso",
            client_id=config.client_id,
            client_secret=SecretStr(config.client_secret),
            discovery_url=discovery_url,
            issuer=config.issuer,
            authorization_endpoint=config.authorization_endpoint,
            token_endpoint=config.token_endpoint,
            userinfo_endpoint=config.userinfo_endpoint,
            jwks_uri=config.jwks_uri,
            scopes=list(config.scopes),
            use_pkce=config.use_pkce,
            override_user_info_on_sign_in=config.override_user_info_on_sign_in,
            disable_sign_up=self._settings.disable_sign_up,
            disable_implicit_sign_up=self._settings.disable_implicit_sign_up,
            token_endpoint_auth_method=config.token_endpoint_auth_method,
            map_profile=self._build_profile_mapper(config),
        )
        return ValidatingOAuthTransport(
            oauth_provider,
            redirect_uri=build_shared_callback_url(
                self._belgie_settings.base_url,
                redirect_uri=self._settings.redirect_uri,
            ),
            issuer=config.issuer,
            discovery_endpoint=discovery_url,
            trusted_origins=self._settings.trusted_idp_origins,
        )

    def _build_profile_mapper(
        self,
        config: OIDCProviderConfig,
    ) -> Callable[[dict[str, object], OAuthTokenSet], OAuthUserInfo]:
        def map_profile(raw_profile: dict[str, object], token_set: OAuthTokenSet) -> OAuthUserInfo:
            mapping = config.claim_mapping
            provider_account_id = self._raw_claim_as_string(raw_profile, mapping.subject)
            if provider_account_id is None:
                raise OAuthError("provider user info missing subject identifier")

            email = self._raw_claim_as_string(raw_profile, mapping.email)
            return OAuthUserInfo(
                provider_account_id=provider_account_id,
                email=email.lower() if email else None,
                email_verified=parse_bool_claim(
                    value=self._raw_claim_as_bool_or_string(raw_profile, mapping.email_verified),
                ),
                name=self._raw_claim_as_string(raw_profile, mapping.name),
                image=self._raw_claim_as_string(raw_profile, mapping.image),
                raw=dict(raw_profile),
            )

        return map_profile

    async def _run_provision_user(
        self,
        *,
        individual: IndividualProtocol[str],
        provider: ProviderT,
        provider_user: OAuthUserInfo,
        token_set: OAuthTokenSet | None,
        created: bool,
    ) -> None:
        if self._settings.provision_user is None:
            return
        if not created and not self._settings.provision_user_on_every_login:
            return

        context = SSOProvisioningContext(
            provider_id=provider.provider_id,
            provider_type=provider.provider_type,
            profile=dict(provider_user.raw),
            token_payload=None if token_set is None else token_set.raw,
            created=created,
        )
        maybe_awaitable = self._settings.provision_user(individual, context)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    async def _assign_provider_organization(
        self,
        *,
        belgie: Belgie,
        provider: ProviderT,
        individual: IndividualProtocol[str],
        provider_user: OAuthUserInfo,
        token_set: OAuthTokenSet | None,
        created: bool,
        db: object,
    ) -> None:
        role = self._settings.organization_default_role
        if self._settings.organization_role_resolver is not None:
            context = SSOProvisioningContext(
                provider_id=provider.provider_id,
                provider_type=provider.provider_type,
                profile=dict(provider_user.raw),
                token_payload=None if token_set is None else token_set.raw,
                created=created,
            )
            resolved_role = self._settings.organization_role_resolver(context)
            if inspect.isawaitable(resolved_role):
                resolved_role = await resolved_role
            if resolved_role:
                role = resolved_role

        await assign_individual_to_provider_organization(
            db=db,
            organization_adapter=self._organization_adapter(belgie),
            provider=provider,
            individual=individual,
            role=role,
        )

    async def _is_trusted_email(
        self,
        *,
        client: BelgieClient,
        provider: ProviderT,
        email: str,
        email_verified: bool,
    ) -> bool:
        if provider.provider_id in self._settings.trusted_providers:
            return True
        if self._settings.trust_email_verified and email_verified:
            return True
        if self._is_default_provider(provider):
            return self._default_provider_matches_email(provider, email)
        return await provider_matches_domain(
            db=client.db,
            adapter=self._settings.adapter,
            provider=provider,
            email=email,
            verified_only=self._settings.domain_verification.enabled,
        )

    async def _refresh_individual_profile(
        self,
        client: BelgieClient,
        provider: ProviderT,
        individual: IndividualProtocol[str],
        provider_user: OAuthUserInfo,
    ) -> IndividualProtocol[str] | None:
        override_user_info = (
            provider.provider_type == "oidc"
            and self._provider_oidc_config(
                provider,
            ).override_user_info_on_sign_in
        )
        updates: dict[str, object] = {}
        if override_user_info and provider_user.name is not None:
            updates["name"] = provider_user.name
        if override_user_info and provider_user.image is not None:
            updates["image"] = provider_user.image
        if individual.email.lower() == (provider_user.email or "").lower() and provider_user.email_verified:
            updates["email_verified_at"] = datetime.now(UTC)
        if not updates:
            return None
        return await client.adapter.update_individual(client.db, individual.id, **updates)

    def _token_updates(self, token_set: OAuthTokenSet | None) -> dict[str, object]:
        if token_set is None:
            return {}
        return {
            "access_token": token_set.access_token,
            "refresh_token": token_set.refresh_token,
            "access_token_expires_at": token_set.access_token_expires_at,
            "refresh_token_expires_at": token_set.refresh_token_expires_at,
            "scope": token_set.scope,
            "token_type": token_set.token_type,
            "id_token": token_set.id_token,
        }

    async def _normalize_form_post_callback(self, request: Request) -> RedirectResponse | None:
        if request.method.upper() != "POST" or self._state_store.has_callback_cookie(request):
            return None
        callback_params = await self._extract_callback_params(request)
        if not callback_params or callback_params.get("SAMLResponse") is not None:
            return None
        parsed = urlparse(str(request.url))
        callback_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", parsed.fragment))
        return RedirectResponse(
            url=append_query_params(callback_url, callback_params),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    async def _extract_callback_params(self, request: Request) -> dict[str, str]:
        params = dict(request.query_params)
        if request.method.upper() == "POST":
            form = await request.form()
            params.update({key: str(value) for key, value in form.items()})
        return params

    def _apply_response_cookies(self, response: Response, cookies: list[ResponseCookie]) -> None:
        for cookie in cookies:
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

    def _response_from_saml_result(self, result: SAMLStartResult | SAMLLogoutResult) -> Response:
        if result.redirect_url is not None:
            return RedirectResponse(url=result.redirect_url, status_code=status.HTTP_302_FOUND)
        if result.form_action is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SAML provider did not return a usable response",
            )
        return self._render_saml_form(result)

    async def _store_saml_session_state(
        self,
        *,
        client: BelgieClient,
        provider: ProviderT,
        session: object,
        provider_user: OAuthUserInfo,
    ) -> None:
        if provider.provider_type != "saml":
            return
        session_id = getattr(session, "id", None)
        if session_id is None:
            return
        session_index = provider_user.raw.get("session_index")
        expires_at = getattr(session, "expires_at", None)
        if not isinstance(expires_at, datetime):
            expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.state_ttl_seconds)
        elif expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        payload: dict[str, str] = {
            "kind": "saml_session",
            "provider_id": provider.provider_id,
            "provider_account_id": provider_user.provider_account_id,
        }
        if isinstance(session_index, str):
            payload["session_index"] = session_index
        await self._replace_oauth_state(
            client=client,
            state=self._saml_session_state_key(session_id),
            expires_at=expires_at,
            payload=payload,
        )
        await self._replace_oauth_state(
            client=client,
            state=self._saml_name_id_state_key(provider.provider_id, provider_user.provider_account_id),
            expires_at=expires_at,
            payload={"kind": "saml_name_id", "session_id": str(session_id)},
        )
        if isinstance(session_index, str):
            await self._replace_oauth_state(
                client=client,
                state=self._saml_idp_session_state_key(provider.provider_id, session_index),
                expires_at=expires_at,
                payload={"kind": "saml_session_index", "session_id": str(session_id)},
            )

    async def _record_saml_assertion(
        self,
        *,
        client: BelgieClient,
        provider: ProviderT,
        saml_profile: object,
    ) -> None:
        assertion_id = getattr(saml_profile, "assertion_id", None)
        if not isinstance(assertion_id, str):
            return
        state = self._saml_assertion_state_key(provider.provider_id, assertion_id)
        if await client.adapter.get_oauth_state(client.db, state) is not None:
            raise OAuthCallbackError("saml_replay_detected", "SAML assertion has already been used")
        await self._replace_oauth_state(
            client=client,
            state=state,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._settings.saml.replay_ttl_seconds),
            payload={"kind": "saml_assertion", "provider_id": provider.provider_id},
        )

    async def _resolve_saml_logout_session_id(
        self,
        *,
        client: BelgieClient,
        provider: ProviderT,
        logout_profile: object,
    ) -> object | None:
        session_index = getattr(logout_profile, "session_index", None)
        if (
            isinstance(session_index, str)
            and (
                lookup := await client.adapter.get_oauth_state(
                    client.db,
                    self._saml_idp_session_state_key(provider.provider_id, session_index),
                )
            )
            is not None
        ):
            return self._payload_session_id(lookup)
        provider_account_id = getattr(logout_profile, "provider_account_id", None)
        if (
            isinstance(provider_account_id, str)
            and (
                lookup := await client.adapter.get_oauth_state(
                    client.db,
                    self._saml_name_id_state_key(provider.provider_id, provider_account_id),
                )
            )
            is not None
        ):
            return self._payload_session_id(lookup)
        return None

    async def _delete_saml_session_state(self, *, client: BelgieClient, session_id: object) -> None:
        session_state_key = self._saml_session_state_key(session_id)
        if (session_state := await client.adapter.get_oauth_state(client.db, session_state_key)) is None:
            return
        provider_id = None
        provider_account_id = None
        session_index = None
        if isinstance(session_state.payload, dict):
            provider_id = session_state.payload.get("provider_id")
            provider_account_id = session_state.payload.get("provider_account_id")
            session_index = session_state.payload.get("session_index")
        await client.adapter.delete_oauth_state(client.db, session_state_key)
        if isinstance(provider_id, str) and isinstance(provider_account_id, str):
            await client.adapter.delete_oauth_state(
                client.db,
                self._saml_name_id_state_key(provider_id, provider_account_id),
            )
        if isinstance(provider_id, str) and isinstance(session_index, str):
            await client.adapter.delete_oauth_state(
                client.db,
                self._saml_idp_session_state_key(provider_id, session_index),
            )

    async def _replace_oauth_state(
        self,
        *,
        client: BelgieClient,
        state: str,
        expires_at: datetime,
        payload: dict[str, str],
    ) -> None:
        if await client.adapter.get_oauth_state(client.db, state) is not None:
            await client.adapter.delete_oauth_state(client.db, state)
        normalized_expiry = expires_at if expires_at.tzinfo is None else expires_at.astimezone(UTC).replace(tzinfo=None)
        await client.adapter.create_oauth_state(
            client.db,
            state=state,
            expires_at=normalized_expiry,
            provider="sso",
            payload=payload,
        )

    def _payload_session_id(self, oauth_state: object) -> UUID | None:
        payload = getattr(oauth_state, "payload", None)
        if not isinstance(payload, dict):
            return None
        session_id = payload.get("session_id")
        if not isinstance(session_id, str):
            return None
        try:
            return UUID(session_id)
        except ValueError:
            return None

    def _clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(
            key=self._belgie_settings.cookie.name,
            domain=self._belgie_settings.cookie.domain,
        )

    def _error_redirect_response(self, *, exc: OAuthError, target: str) -> RedirectResponse:
        return RedirectResponse(
            url=append_query_params(
                target,
                {
                    "error": exc.code if isinstance(exc, OAuthCallbackError) else "oauth_callback_failed",
                    "error_description": str(exc),
                },
            ),
            status_code=status.HTTP_302_FOUND,
        )

    def _error_redirect_target(self, oauth_state: ConsumedOAuthState) -> str:
        if oauth_state.error_redirect_url:
            return oauth_state.error_redirect_url
        if oauth_state.redirect_url:
            return oauth_state.redirect_url
        return self._belgie_settings.urls.signin_redirect

    def _normalize_redirect_target(self, target: str | None) -> str | None:
        return normalize_redirect_target(
            target,
            base_url=self._belgie_settings.base_url,
            trusted_origins=self._settings.trusted_origins,
        )

    @staticmethod
    def _raise_discovery_http_exception(exc: DiscoveryError) -> None:
        if exc.code in {"discovery_timeout", "discovery_unexpected_error"}:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OIDC discovery failed: {exc}",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OIDC discovery failed: {exc}",
        ) from exc

    def _provider_oidc_config(self, provider: ProviderT) -> OIDCProviderConfig:
        if provider.oidc_config is None:
            raise OAuthError("provider is missing oidc config")
        return deserialize_oidc_config(provider.oidc_config)

    def _provider_saml_config(self, provider: ProviderT) -> SAMLProviderConfig:
        if provider.saml_config is None:
            raise OAuthError("provider is missing saml config")
        return deserialize_saml_config(provider.saml_config)

    def _payload_provider_id(self, oauth_state: ConsumedOAuthState) -> str:
        if not isinstance(oauth_state.payload, dict):
            raise OAuthCallbackError("state_mismatch", "OAuth state payload is missing provider_id")
        provider_id = oauth_state.payload.get("provider_id")
        if not isinstance(provider_id, str):
            raise OAuthCallbackError("state_mismatch", "OAuth state payload is missing provider_id")
        return self._normalize_provider_id_or_400(provider_id)

    def _payload_request_id(self, oauth_state: ConsumedOAuthState) -> str | None:
        if not isinstance(oauth_state.payload, dict):
            return None
        request_id = oauth_state.payload.get("request_id")
        return request_id if isinstance(request_id, str) else None

    def _render_saml_form(self, start_result: SAMLStartResult | SAMLLogoutResult) -> HTMLResponse:
        form_action = getattr(start_result, "form_action", None)
        form_fields = getattr(start_result, "form_fields", {})
        if not isinstance(form_action, str) or not isinstance(form_fields, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid SAML sign-in response",
            )

        inputs = "\n".join(
            f'<input type="hidden" name="{html.escape(name, quote=True)}" value="{html.escape(value, quote=True)}"/>'
            for name, value in form_fields.items()
            if isinstance(name, str) and isinstance(value, str)
        )
        return HTMLResponse(
            content=(
                '<html><body onload="document.forms[0].submit()">'
                f'<form method="post" action="{html.escape(form_action, quote=True)}">{inputs}</form>'
                "</body></html>"
            ),
        )

    def _saml_callback_url(self, provider_id: str) -> str:
        return build_provider_callback_url(self._belgie_settings.base_url, provider_id=provider_id)

    def _saml_slo_url(self, provider_id: str) -> str:
        callback_url = self._saml_callback_url(provider_id)
        parsed = urlparse(callback_url)
        return urlunparse(parsed._replace(path=parsed.path.replace("/callback/", "/slo/", 1), query="", fragment=""))

    def _normalize_provider_id_or_400(self, provider_id: str) -> str:
        try:
            return normalize_provider_id(provider_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @staticmethod
    def _raw_claim_as_string(raw_profile: dict[str, object], claim_name: str) -> str | None:
        value = raw_profile.get(claim_name)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _raw_claim_as_bool_or_string(raw_profile: dict[str, object], claim_name: str) -> str | bool | None:
        value = raw_profile.get(claim_name)
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        return str(value)

    async def _ensure_provider_verified_or_http(self, *, client: BelgieClient, provider: ProviderT) -> None:
        if not self._settings.domain_verification.enabled:
            return
        if await self._provider_has_verified_domain(client=client, provider=provider):
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider must have a verified domain before sign-in",
        )

    async def _ensure_provider_verified_or_oauth_error(self, *, client: BelgieClient, provider: ProviderT) -> None:
        if not self._settings.domain_verification.enabled:
            return
        if await self._provider_has_verified_domain(client=client, provider=provider):
            return
        raise OAuthCallbackError("provider_not_verified", "provider must have a verified domain before sign-in")

    async def _provider_has_verified_domain(self, *, client: BelgieClient, provider: ProviderT) -> bool:
        if self._is_default_provider(provider):
            return True
        domains = await self._settings.adapter.list_domains_for_provider(client.db, sso_provider_id=provider.id)
        return any(domain.verified_at is not None for domain in domains)

    def _default_provider(self, providers: list[ProviderT]) -> ProviderT | None:
        if self._settings.default_sso is None:
            return None
        normalized_default = self._normalize_provider_id_or_400(self._settings.default_sso)
        for provider in providers:
            if provider.provider_id == normalized_default:
                return provider
        return None

    def _default_provider_for_provider_id(self, provider_id: str) -> _DefaultProvider | None:
        for provider in self._settings.default_providers:
            if provider.provider_id == provider_id:
                return self._build_default_provider(provider)
        return None

    def _default_provider_for_domain(self, domain: str) -> _DefaultProvider | None:
        for provider in self._settings.default_providers:
            if provider.domain == domain:
                return self._build_default_provider(provider)
        return None

    def _build_default_provider(self, provider: object) -> _DefaultProvider:
        oidc_config = getattr(provider, "oidc_config", None)
        saml_config = getattr(provider, "saml_config", None)
        provider_type = "oidc" if oidc_config is not None else "saml"
        return _DefaultProvider(
            id=uuid5(NAMESPACE_URL, f"belgie-sso-default:{provider.provider_id}"),
            organization_id=None,
            created_by_individual_id=None,
            provider_type=provider_type,
            provider_id=provider.provider_id,
            issuer=provider.issuer,
            oidc_config=serialize_oidc_config(oidc_config) if oidc_config is not None else None,
            saml_config=serialize_saml_config(saml_config) if saml_config is not None else None,
            created_at=datetime.fromtimestamp(0, UTC),
            updated_at=datetime.fromtimestamp(0, UTC),
            domain=provider.domain,
        )

    @staticmethod
    def _is_default_provider(provider: object) -> bool:
        return isinstance(provider, _DefaultProvider)

    def _default_provider_matches_email(self, provider: object, email: str) -> bool:
        if not isinstance(provider, _DefaultProvider):
            return False
        if not (domain := extract_email_domain(email)):
            return False
        return provider.domain == domain

    @staticmethod
    def _saml_session_state_key(session_id: object) -> str:
        return f"saml-session:{session_id}"

    @staticmethod
    def _saml_name_id_state_key(provider_id: str, provider_account_id: str) -> str:
        return f"saml-name-id:{provider_id}:{provider_account_id}"

    @staticmethod
    def _saml_idp_session_state_key(provider_id: str, session_index: str) -> str:
        return f"saml-session-index:{provider_id}:{session_index}"

    @staticmethod
    def _saml_assertion_state_key(provider_id: str, assertion_id: str) -> str:
        return f"saml-assertion:{provider_id}:{assertion_id}"

    @staticmethod
    def _saml_logout_request_state_key(request_id: str) -> str:
        return f"saml-logout:{request_id}"
