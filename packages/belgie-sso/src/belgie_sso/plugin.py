import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

import httpx
import jwt
from belgie_core.core.client import BelgieClient
from belgie_core.core.exceptions import InvalidStateError, OAuthError
from belgie_core.core.plugin import AfterAuthenticateHook, AuthenticatedProfile, PluginClient
from belgie_core.utils.crypto import generate_state_token
from belgie_organization.plugin import OrganizationPlugin
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.sso import OIDCProviderConfig, SSODomainProtocol, SSOProviderProtocol
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import SecurityScopes
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from belgie_sso.client import SSOClient
from belgie_sso.discovery import ensure_runtime_discovery
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
    generate_pkce_code_challenge,
    generate_pkce_code_verifier,
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


@dataclass(slots=True, kw_only=True)
class NormalizedOIDCProfile:
    subject: str
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    user_info: dict[str, Any]


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
        if profile.provider not in set(self._settings.domain_assignment_providers) or not profile.email_verified:
            return

        organization_plugin = self._ensure_organization_plugin(belgie)
        await assign_individual_by_verified_domain(
            db=client.db,
            adapter=self._settings.adapter,
            organization_adapter=organization_plugin.settings.adapter,
            individual=individual,
            email=profile.email,
            provisioning_options=self._settings.organization_provisioning,
        )

    async def get_user_info(
        self,
        *,
        config: OIDCProviderConfig,
        access_token: str,
    ) -> dict[str, Any]:
        if not config.userinfo_endpoint:
            msg = "OIDC configuration is missing userinfo_endpoint"
            raise OAuthError(msg)
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
        return {str(key): value for key, value in data.items()}

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
        type BelgieClientDep = Annotated[BelgieClient, Depends(belgie)]

        @router.get("/signin")
        async def signin(  # noqa: PLR0913
            _request: Request,
            client: BelgieClientDep,
            provider_id: Annotated[str | None, Query()] = None,
            email: Annotated[str | None, Query()] = None,
            login_hint: Annotated[str | None, Query()] = None,
            redirect_to: Annotated[str | None, Query()] = None,
            request_sign_up: Annotated[bool, Query()] = False,  # noqa: FBT002
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
            config = await self._get_provider_config(
                provider=provider,
                require_userinfo_or_jwks=False,
            )
            code_verifier = generate_pkce_code_verifier() if config.pkce else None
            code_challenge = generate_pkce_code_challenge(code_verifier) if code_verifier is not None else None
            await client.adapter.create_oauth_state(
                client.db,
                state=state,
                expires_at=(datetime.now(UTC) + timedelta(seconds=self._settings.state_ttl_seconds)).replace(
                    tzinfo=None,
                ),
                code_verifier=code_verifier,
                redirect_url=redirect_url,
                request_sign_up=request_sign_up,
            )
            authorization_url = build_authorization_url(
                authorization_endpoint=config.authorization_endpoint,
                client_id=config.client_id,
                redirect_uri=build_provider_callback_url(
                    self._belgie_settings.base_url,
                    provider_id=provider.provider_id,
                ),
                scopes=list(config.scopes),
                state=state,
                login_hint=(login_hint or email).lower() if (login_hint or email) else None,
                code_challenge=code_challenge,
                code_challenge_method="S256" if code_challenge else None,
            )
            return RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)

        @router.get("/callback/{provider_id}")
        async def callback(
            provider_id: Annotated[str, Path(min_length=1)],
            code: Annotated[str, Query(min_length=1)],
            state: Annotated[str, Query(min_length=1)],
            request: Request,
            client: BelgieClientDep,
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

            config = await self._get_provider_config(provider=provider)
            tokens = await self._exchange_code_for_tokens(
                config=config,
                code=code,
                redirect_uri=build_provider_callback_url(
                    self._belgie_settings.base_url,
                    provider_id=provider.provider_id,
                ),
                code_verifier=getattr(oauth_state, "code_verifier", None),
            )
            claims = await self._get_claims(
                provider=provider,
                config=config,
                tokens=tokens,
            )
            profile = self._normalize_profile(
                claims=claims,
                config=config,
            )

            if not await provider_matches_verified_domain(
                db=client.db,
                adapter=self._settings.adapter,
                provider=provider,
                email=profile.email,
            ):
                msg = "email domain is not verified for this provider"
                raise OAuthError(msg)

            existing_user = await client.adapter.get_individual_by_email(
                client.db,
                profile.email.lower(),
            )
            request_sign_up = bool(getattr(oauth_state, "request_sign_up", False))
            if existing_user is None and self._settings.disable_implicit_sign_up and not request_sign_up:
                msg = "implicit sign up is disabled for this SSO provider"
                raise OAuthError(msg)

            user, session, is_register = await self._resolve_user_session(
                client=client,
                request=request,
                email=profile.email,
                profile=profile,
                existing_user=existing_user,
                config=config,
            )

            await client.upsert_oauth_account(
                individual_id=user.id,
                provider=as_account_provider(provider.provider_id),
                provider_account_id=profile.subject,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_at=tokens.expires_at,
                scope=tokens.scope,
                token_type=tokens.token_type,
                id_token=tokens.id_token,
            )

            if self._settings.provision_user and (is_register or self._settings.provision_user_on_every_login):
                await self._settings.provision_user(
                    user=user,
                    user_info=profile.user_info,
                    token=tokens,
                    provider=provider,
                )

            await assign_individual_to_provider_organization(
                db=client.db,
                organization_adapter=organization_plugin.settings.adapter,
                provider=provider,
                individual=user,
                provisioning_options=self._settings.organization_provisioning,
                email=profile.email,
                user_info=profile.user_info,
                token=tokens,
            )

            await belgie.after_authenticate(
                client=client,
                request=request,
                individual=user,
                profile=AuthenticatedProfile(
                    provider=as_account_provider(provider.provider_id),
                    provider_account_id=profile.subject,
                    email=profile.email,
                    email_verified=profile.email_verified,
                    name=profile.name,
                    image=profile.image,
                ),
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

    async def _get_provider_config(
        self,
        *,
        provider: ProviderT,
        require_userinfo_or_jwks: bool = True,
    ) -> OIDCProviderConfig:
        stored_config = deserialize_oidc_config(provider.oidc_config)
        try:
            return await ensure_runtime_discovery(
                config=stored_config,
                issuer=provider.issuer,
                timeout_seconds=self._settings.discovery_timeout_seconds,
                require_userinfo_or_jwks=require_userinfo_or_jwks,
            )
        except ValueError as exc:
            raise OAuthError(str(exc)) from exc

    async def _get_claims(
        self,
        *,
        provider: ProviderT,
        config: OIDCProviderConfig,
        tokens: TokenResponse,
    ) -> dict[str, Any]:
        if config.userinfo_endpoint:
            return await self.get_user_info(
                config=config,
                access_token=tokens.access_token,
            )
        return await self._get_id_token_claims(
            provider=provider,
            config=config,
            id_token=tokens.id_token,
        )

    async def _get_id_token_claims(
        self,
        *,
        provider: ProviderT,
        config: OIDCProviderConfig,
        id_token: str | None,
    ) -> dict[str, Any]:
        if not id_token:
            msg = "missing id_token in token response"
            raise OAuthError(msg)
        if not config.jwks_uri:
            msg = "OIDC configuration is missing jwks_uri"
            raise OAuthError(msg)
        try:
            jwk_client = PyJWKClient(config.jwks_uri)
            signing_key = await asyncio.to_thread(
                jwk_client.get_signing_key_from_jwt,
                id_token,
            )
            header = jwt.get_unverified_header(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=[str(header.get("alg", "RS256"))],
                audience=config.client_id,
                issuer=provider.issuer,
            )
        except (PyJWTError, ValueError) as exc:
            msg = "id_token verification failed"
            raise OAuthError(msg) from exc
        if not isinstance(claims, dict):
            msg = "id_token payload must be a JSON object"
            raise OAuthError(msg)
        return claims

    def _normalize_profile(
        self,
        *,
        claims: dict[str, Any],
        config: OIDCProviderConfig,
    ) -> NormalizedOIDCProfile:
        mapping = config.claim_mapping
        subject = claims.get(mapping.subject)
        email = claims.get(mapping.email)
        if not isinstance(subject, str) or not isinstance(email, str):
            msg = "OIDC claims are missing required subject/email values"
            raise OAuthError(msg)

        name = claims.get(mapping.name)
        image = claims.get(mapping.image)
        email_verified_value = claims.get(mapping.email_verified) if mapping.email_verified in claims else None
        email_verified = parse_bool_claim(value=email_verified_value) if self._settings.trust_email_verified else False

        normalized_user_info = dict(claims)
        normalized_user_info.update(
            {key: claims.get(source) for key, source in mapping.extra_fields.items()},
        )
        normalized_user_info.update(
            {
                "id": subject,
                "email": email.lower(),
                "email_verified": email_verified,
                "name": name if isinstance(name, str) else None,
                "image": image if isinstance(image, str) else None,
            },
        )

        return NormalizedOIDCProfile(
            subject=subject,
            email=email.lower(),
            email_verified=email_verified,
            name=name if isinstance(name, str) else None,
            image=image if isinstance(image, str) else None,
            user_info=normalized_user_info,
        )

    async def _resolve_user_session(  # noqa: PLR0913
        self,
        *,
        client: BelgieClient,
        request: Request,
        email: str,
        profile: NormalizedOIDCProfile,
        existing_user: Any,  # noqa: ANN401
        config: OIDCProviderConfig,
    ) -> tuple[Any, Any, bool]:
        trusted_email_verified_at = (
            datetime.now(UTC) if self._settings.trust_email_verified and profile.email_verified else None
        )
        effective_override_user_info = config.override_user_info or self._settings.default_override_user_info

        if existing_user is None:
            user, session = await client.sign_up(
                email.lower(),
                request=request,
                name=profile.name,
                image=profile.image,
                email_verified_at=trusted_email_verified_at,
            )
            return user, session, True

        updates: dict[str, Any] = {}
        if effective_override_user_info:
            if profile.name is not None:
                updates["name"] = profile.name
            if profile.image is not None:
                updates["image"] = profile.image
        if trusted_email_verified_at is not None and getattr(existing_user, "email_verified_at", None) is None:
            updates["email_verified_at"] = trusted_email_verified_at

        user = existing_user
        if updates:
            updated = await client.adapter.update_individual(
                client.db,
                existing_user.id,
                **updates,
            )
            if updated is not None:
                user = updated

        session = await client.sign_in_individual(
            user,
            request=request,
        )
        return user, session, False

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

        sso_domain = await self._settings.adapter.get_best_verified_domain(client.db, domain=domain)
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
        config: OIDCProviderConfig,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
    ) -> TokenResponse:
        if not config.token_endpoint:
            msg = "OIDC configuration is missing token_endpoint"
            raise OAuthError(msg)

        payload = {
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if config.pkce:
            if code_verifier is None:
                msg = "missing PKCE code_verifier for OAuth state"
                raise OAuthError(msg)
            payload["code_verifier"] = code_verifier
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
