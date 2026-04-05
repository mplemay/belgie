import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

import httpx
from belgie_core.core.client import BelgieClient
from belgie_core.core.exceptions import InvalidStateError, OAuthError
from belgie_core.core.plugin import AfterAuthenticateHook, AuthenticatedProfile, PluginClient
from belgie_core.utils.crypto import generate_state_token
from belgie_organization.plugin import OrganizationPlugin
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.sso import SSODomainProtocol, SSOProviderProtocol
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes

from belgie_sso.client import SSOClient
from belgie_sso.org_assignment import (
    assign_individual_by_verified_domain,
    assign_individual_to_provider_organization,
    provider_matches_verified_domain,
)
from belgie_sso.utils import (
    as_account_provider,
    build_authorization_url,
    build_provider_callback_url,
    deserialize_oidc_config,
    extract_email_domain,
    normalize_provider_id,
    normalize_return_to,
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
        belgie_settings: "BelgieSettings",
        settings: "EnterpriseSSO[ProviderT, DomainT]",
    ) -> None:
        self._belgie_settings = belgie_settings
        self._settings = settings
        self._resolve_client: (
            Callable[
                ...,
                Awaitable[SSOClient[ProviderT, DomainT, OrganizationProtocol, MemberProtocol, InvitationProtocol]],
            ]
            | None
        ) = None
        self._organization_plugin: OrganizationPlugin | None = None

    @property
    def settings(self) -> "EnterpriseSSO[ProviderT, DomainT]":
        return self._settings

    def _ensure_organization_plugin(self, belgie: "Belgie") -> OrganizationPlugin:
        if self._organization_plugin is not None:
            return self._organization_plugin

        organization_plugin = next(
            (plugin for plugin in belgie.plugins if isinstance(plugin, OrganizationPlugin)),
            None,
        )
        if organization_plugin is None:
            msg = "EnterpriseSSO requires the belgie-organization plugin"
            raise RuntimeError(msg)
        self._organization_plugin = organization_plugin
        return organization_plugin

    def _ensure_dependency_resolver(self, belgie: "Belgie") -> None:
        if self._resolve_client is not None:
            return

        organization_plugin = self._ensure_organization_plugin(belgie)

        async def resolve_client(
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> SSOClient[ProviderT, DomainT, OrganizationProtocol, MemberProtocol, InvitationProtocol]:
            current_individual = await client.get_individual(SecurityScopes(), request)
            return SSOClient(
                client=client,
                settings=self._settings,
                organization_adapter=organization_plugin.settings.adapter,
                current_individual=current_individual,
            )

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    async def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> SSOClient[ProviderT, DomainT, OrganizationProtocol, MemberProtocol, InvitationProtocol]:
        if self._resolve_client is None:
            msg = "SSOPlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            raise RuntimeError(msg)
        return await self._resolve_client(*args, **kwargs)

    async def after_authenticate(
        self,
        *,
        belgie: "Belgie",
        client: BelgieClient,
        request: Request,  # noqa: ARG002
        individual: "IndividualProtocol[str]",
        profile: AuthenticatedProfile,
    ) -> None:
        if profile.provider not in {"google", "microsoft"} or not profile.email_verified:
            return

        organization_plugin = self._ensure_organization_plugin(belgie)
        await assign_individual_by_verified_domain(
            db=client.db,
            adapter=self._settings.adapter,
            organization_adapter=organization_plugin.settings.adapter,
            individual=individual,
            email=profile.email,
        )

    async def get_user_info(
        self,
        *,
        provider: ProviderT,
        access_token: str,
    ) -> dict[str, str | bool]:
        config = deserialize_oidc_config(provider.oidc_config)
        async with httpx.AsyncClient(timeout=self._settings.discovery_timeout_seconds) as http_client:
            response = await http_client.get(
                config.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            msg = "userinfo response must be a JSON object"
            raise OAuthError(msg)

        filtered: dict[str, str | bool] = {}
        for key, value in data.items():
            if isinstance(value, (str, bool)):
                filtered[str(key)] = value
        return filtered

    def _normalize_provider_id_or_400(self, provider_id: str) -> str:
        try:
            return normalize_provider_id(provider_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    def router(self, belgie: "Belgie") -> APIRouter:
        self._ensure_dependency_resolver(belgie)
        organization_plugin = self._ensure_organization_plugin(belgie)
        router = APIRouter(prefix="/provider/sso", tags=["auth", "sso"])

        @router.get("/signin")
        async def signin(
            _request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
            provider_id: Annotated[str | None, Query()] = None,
            email: Annotated[str | None, Query()] = None,
            redirect_to: Annotated[str | None, Query()] = None,
        ) -> RedirectResponse:
            if not provider_id and not email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="provider_id or email is required",
                )

            provider = await self._resolve_provider_for_signin(
                client=client,
                provider_id=provider_id,
                email=email,
            )
            state = generate_state_token()
            redirect_url = normalize_return_to(redirect_to, base_url=self._belgie_settings.base_url)
            await client.adapter.create_oauth_state(
                client.db,
                state=state,
                expires_at=(datetime.now(UTC) + timedelta(seconds=self._settings.state_ttl_seconds)).replace(
                    tzinfo=None,
                ),
                redirect_url=redirect_url,
            )

            config = deserialize_oidc_config(provider.oidc_config)
            authorization_url = build_authorization_url(
                authorization_endpoint=config.authorization_endpoint,
                client_id=config.client_id,
                redirect_uri=build_provider_callback_url(
                    self._belgie_settings.base_url,
                    provider_id=provider.provider_id,
                ),
                scopes=list(config.scopes),
                state=state,
                login_hint=email.lower() if email else None,
            )
            return RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)

        @router.get("/callback/{provider_id}")
        async def callback(
            provider_id: str,
            code: Annotated[str, Query(min_length=1)],
            state: Annotated[str, Query(min_length=1)],
            request: Request,
            client: Annotated[BelgieClient, Depends(belgie)],
        ) -> RedirectResponse:
            oauth_state = await client.adapter.get_oauth_state(client.db, state)
            if oauth_state is None:
                msg = "Invalid OAuth state"
                raise InvalidStateError(msg)
            await client.adapter.delete_oauth_state(client.db, state)

            normalized_id = self._normalize_provider_id_or_400(provider_id)
            provider = await self._settings.adapter.get_provider_by_provider_id(
                client.db,
                provider_id=normalized_id,
            )
            if provider is None:
                msg = "SSO provider not found"
                raise OAuthError(msg)

            tokens = await self._exchange_code_for_tokens(
                provider=provider,
                code=code,
                redirect_uri=build_provider_callback_url(
                    self._belgie_settings.base_url,
                    provider_id=provider.provider_id,
                ),
            )
            claims = await self.get_user_info(provider=provider, access_token=tokens.access_token)
            config = deserialize_oidc_config(provider.oidc_config)
            mapping = config.claim_mapping
            email = claims.get(mapping.email)
            subject = claims.get(mapping.subject)
            if not isinstance(email, str) or not isinstance(subject, str):
                msg = "userinfo response is missing required claims"
                raise OAuthError(msg)

            if not await provider_matches_verified_domain(
                db=client.db,
                adapter=self._settings.adapter,
                provider=provider,
                email=email,
            ):
                msg = "email domain is not verified for this provider"
                raise OAuthError(msg)

            name = claims.get(mapping.name)
            image = claims.get(mapping.image)
            email_verified = parse_bool_claim(
                value=claims.get(mapping.email_verified) if mapping.email_verified in claims else None,
            )

            user, session = await client.sign_up(
                email.lower(),
                request=request,
                name=name if isinstance(name, str) else None,
                image=image if isinstance(image, str) else None,
                email_verified_at=datetime.now(UTC) if email_verified else None,
            )

            await client.upsert_oauth_account(
                individual_id=user.id,
                provider=as_account_provider(provider.provider_id),
                provider_account_id=subject,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_at=tokens.expires_at,
                scope=tokens.scope,
                token_type=tokens.token_type,
                id_token=tokens.id_token,
            )

            await assign_individual_to_provider_organization(
                db=client.db,
                organization_adapter=organization_plugin.settings.adapter,
                provider=provider,
                individual=user,
            )

            response = RedirectResponse(
                url=oauth_state.redirect_url or belgie.settings.urls.signin_redirect,
                status_code=status.HTTP_302_FOUND,
            )
            return client.create_session_cookie(session, response)

        return router

    def public(self, belgie: "Belgie") -> APIRouter | None:
        self._ensure_organization_plugin(belgie)
        return None

    async def _resolve_provider_for_signin(
        self,
        *,
        client: BelgieClient,
        provider_id: str | None,
        email: str | None,
    ) -> ProviderT:
        if provider_id:
            provider = await self._settings.adapter.get_provider_by_provider_id(
                client.db,
                provider_id=self._normalize_provider_id_or_400(provider_id),
            )
            if provider is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="provider not found",
                )
            domains = await self._settings.adapter.list_domains_for_provider(
                client.db,
                sso_provider_id=provider.id,
            )
            if not any(domain.verified_at is not None for domain in domains):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="provider has no verified domains",
                )
            return provider

        if email is None or not (domain := extract_email_domain(email)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email must contain a valid domain",
            )

        sso_domain = await self._settings.adapter.get_verified_domain(client.db, domain=domain)
        if sso_domain is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no verified provider found for email domain",
            )
        provider = await self._settings.adapter.get_provider_by_id(
            client.db,
            sso_provider_id=sso_domain.sso_provider_id,
        )
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="provider not found",
            )
        return provider

    async def _exchange_code_for_tokens(
        self,
        *,
        provider: ProviderT,
        code: str,
        redirect_uri: str,
    ) -> TokenResponse:
        config = deserialize_oidc_config(provider.oidc_config)

        payload = {
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        auth = None
        if config.token_endpoint_auth_method == "client_secret_post":  # noqa: S105
            payload["client_id"] = config.client_id
            payload["client_secret"] = config.client_secret
        else:
            auth = (config.client_id, config.client_secret)

        async with httpx.AsyncClient(timeout=self._settings.discovery_timeout_seconds) as http_client:
            if auth is None:
                response = await http_client.post(config.token_endpoint, data=payload)
            else:
                response = await http_client.post(config.token_endpoint, data=payload, auth=auth)
            response.raise_for_status()
            data = response.json()

        if "access_token" not in data:
            msg = "missing access_token in token response"
            raise OAuthError(msg)

        expires_at = None
        if isinstance(data.get("expires_in"), int):
            expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])

        return TokenResponse(
            access_token=str(data["access_token"]),
            token_type=str(data["token_type"]) if data.get("token_type") is not None else None,
            refresh_token=str(data["refresh_token"]) if data.get("refresh_token") is not None else None,
            scope=str(data["scope"]) if data.get("scope") is not None else None,
            id_token=str(data["id_token"]) if data.get("id_token") is not None else None,
            expires_at=expires_at,
        )
