# ruff: noqa: ARG001, C901, EM101, FAST002, FBT002, PLR0913, PLR0915, TRY003, TRY300

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlparse, urlunparse

from belgie_core.core.client import BelgieClient  # noqa: TC002
from belgie_core.core.exceptions import InvalidStateError, OAuthError
from belgie_core.core.plugin import AfterAuthenticateHook, AuthenticatedProfile, PluginClient
from belgie_core.utils.crypto import generate_state_token
from belgie_oauth._config import OAuthProvider
from belgie_oauth._errors import OAuthCallbackError
from belgie_oauth._helpers import append_query_params, generate_code_verifier
from belgie_oauth._models import ConsumedOAuthState, OAuthTokenSet, OAuthUserInfo, PendingOAuthState, ResponseCookie
from belgie_oauth._state import AdapterOAuthStateStore
from belgie_oauth._transport import OAuthTransport
from belgie_organization.plugin import OrganizationPlugin
from belgie_proto.sso import OIDCProviderConfig, SAMLProviderConfig, SSODomainProtocol, SSOProviderProtocol
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import SecurityScopes
from pydantic import SecretStr

from belgie_sso.client import SSOClient
from belgie_sso.models import SSOProvisioningContext
from belgie_sso.org_assignment import (
    assign_individual_by_verified_domain,
    assign_individual_to_provider_organization,
    provider_matches_verified_domain,
)
from belgie_sso.saml import NullSAMLEngine, SAMLStartResult
from belgie_sso.utils import (
    as_account_provider,
    build_provider_callback_url,
    build_shared_callback_url,
    choose_best_verified_domain_match,
    deserialize_oidc_config,
    deserialize_saml_config,
    extract_email_domain,
    normalize_domain,
    normalize_provider_id,
    normalize_redirect_target,
    parse_bool_claim,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.core.individual import IndividualProtocol

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
        self._saml_engine = settings.saml_engine or NullSAMLEngine()
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
        if profile.provider not in {"google", "microsoft"} or not profile.email_verified:
            return

        await assign_individual_by_verified_domain(
            db=client.db,
            adapter=self._settings.adapter,
            organization_adapter=self._organization_adapter(belgie),
            individual=individual,
            email=profile.email,
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
        redirect_to: str | None,
        error_redirect_url: str | None,
        new_user_redirect_url: str | None,
        request_sign_up: bool,
        scopes: list[str] | None,
    ) -> RedirectResponse:
        transport = self._build_oidc_transport(provider)
        state = generate_state_token()
        code_verifier = generate_code_verifier() if transport.config.use_pkce else None
        nonce = generate_state_token() if transport.should_use_nonce(scopes) else None
        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.state_ttl_seconds)
        cookies = await self._state_store.create_authorization_state(
            client,
            PendingOAuthState(
                state=state,
                provider="sso",
                individual_id=None,
                code_verifier=code_verifier,
                nonce=nonce,
                intent="signin",
                redirect_url=self._normalize_redirect_target(redirect_to),
                error_redirect_url=self._normalize_redirect_target(error_redirect_url),
                new_user_redirect_url=self._normalize_redirect_target(new_user_redirect_url),
                payload={
                    "provider_id": provider.provider_id,
                    "flow": "oidc",
                },
                request_sign_up=request_sign_up,
                expires_at=expires_at,
            ),
        )
        authorization_url = await transport.generate_authorization_url(
            state,
            scopes=scopes,
            authorization_params={"login_hint": email.lower()} if email else None,
            code_verifier=code_verifier,
            nonce=nonce,
        )
        response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
        self._apply_response_cookies(response, cookies)
        return response

    async def _complete_oidc_callback(
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

            transport = self._build_oidc_transport(provider)
            metadata = await transport.resolve_server_metadata()
            transport.validate_issuer_parameter(callback_params.get("iss"), metadata)

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
            if consumed_state and consumed_state.error_redirect_url:
                response = self._error_redirect_response(exc=exc, target=consumed_state.error_redirect_url)
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
            if not (relay_state := callback_params.get("RelayState")):
                raise OAuthCallbackError("state_mismatch", "missing SAML RelayState")

            oauth_state = await client.adapter.get_oauth_state(client.db, relay_state)
            if oauth_state is None:
                raise InvalidStateError("Invalid OAuth state")
            await client.adapter.delete_oauth_state(client.db, relay_state)
            consumed_state = ConsumedOAuthState.from_model(oauth_state)

            resolved_provider_id = self._payload_provider_id(consumed_state)
            if provider_id is not None and self._normalize_provider_id_or_400(provider_id) != resolved_provider_id:
                raise OAuthCallbackError("state_mismatch", "SAML state provider mismatch")

            provider = await self._get_provider_by_provider_id(client=client, provider_id=resolved_provider_id)
            if provider.provider_type != "saml":
                raise OAuthCallbackError("state_mismatch", "SAML state provider mismatch")

            request.state.oauth_state = consumed_state
            request.state.oauth_payload = consumed_state.payload

            try:
                saml_profile = await self._saml_engine.finish_signin(
                    provider=provider,
                    config=self._provider_saml_config(provider),
                    request=request,
                    relay_state=relay_state,
                    request_id=self._payload_request_id(consumed_state),
                )
            except RuntimeError as exc:
                raise OAuthError(str(exc)) from exc

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
                    raw=dict(saml_profile.raw),
                ),
                token_set=None,
            )
        except OAuthError as exc:
            if consumed_state and consumed_state.error_redirect_url:
                return self._error_redirect_response(exc=exc, target=consumed_state.error_redirect_url)
            raise

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

        redirect_url = belgie.settings.urls.signin_redirect
        if created and oauth_state.new_user_redirect_url:
            redirect_url = oauth_state.new_user_redirect_url
        elif oauth_state.redirect_url:
            redirect_url = oauth_state.redirect_url

        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        return client.create_session_cookie(session, response)

    async def _resolve_provider_for_signin(
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

        try:
            matched_domain = choose_best_verified_domain_match(
                domain=resolved_domain,
                domains=await self._settings.adapter.list_verified_domains_matching(
                    client.db,
                    domain=resolved_domain,
                ),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        if matched_domain is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no verified provider found for domain",
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

    async def _get_provider_by_provider_id(self, *, client: BelgieClient, provider_id: str) -> ProviderT:
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
        if discovery_url is None and (config.authorization_endpoint is None or config.token_endpoint is None):
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
        return OAuthTransport(
            oauth_provider,
            redirect_uri=build_shared_callback_url(
                self._belgie_settings.base_url,
                redirect_uri=self._settings.redirect_uri,
            ),
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
        if self._settings.trust_email_verified and email_verified:
            return True
        return await provider_matches_verified_domain(
            db=client.db,
            adapter=self._settings.adapter,
            provider=provider,
            email=email,
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

    def _error_redirect_response(self, *, exc: OAuthError, target: str) -> RedirectResponse:
        return RedirectResponse(
            url=append_query_params(
                target,
                {
                    "error": exc.code if isinstance(exc, OAuthCallbackError) else "oauth_callback_failed",
                },
            ),
            status_code=status.HTTP_302_FOUND,
        )

    def _normalize_redirect_target(self, target: str | None) -> str | None:
        return normalize_redirect_target(
            target,
            base_url=self._belgie_settings.base_url,
            trusted_origins=self._settings.trusted_origins,
        )

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

    def _render_saml_form(self, start_result: SAMLStartResult) -> HTMLResponse:
        form_action = getattr(start_result, "form_action", None)
        form_fields = getattr(start_result, "form_fields", {})
        if not isinstance(form_action, str) or not isinstance(form_fields, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid SAML sign-in response",
            )

        inputs = "\n".join(
            f'<input type="hidden" name="{name}" value="{value}"/>'
            for name, value in form_fields.items()
            if isinstance(name, str) and isinstance(value, str)
        )
        return HTMLResponse(
            content=(
                '<html><body onload="document.forms[0].submit()">'
                f'<form method="post" action="{form_action}">{inputs}</form>'
                "</body></html>"
            ),
        )

    def _saml_callback_url(self, provider_id: str) -> str:
        return build_provider_callback_url(self._belgie_settings.base_url, provider_id=provider_id)

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
