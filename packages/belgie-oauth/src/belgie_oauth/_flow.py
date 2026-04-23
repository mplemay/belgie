from __future__ import annotations

# ruff: noqa: EM101
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypedDict
from urllib.parse import urlparse, urlunparse

from belgie_core.core.exceptions import OAuthError
from belgie_core.core.plugin import AuthenticatedProfile
from belgie_core.utils.crypto import generate_state_token
from fastapi import Request, status
from fastapi.responses import RedirectResponse

from belgie_oauth._errors import OAuthCallbackError
from belgie_oauth._helpers import append_query_params, generate_code_verifier
from belgie_oauth._models import (
    ConsumedOAuthState,
    OAuthLinkedAccount,
    OAuthTokenSet,
    OAuthUserInfo,
    PendingOAuthState,
)

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_core.core.client import BelgieClient
    from belgie_proto.core.individual import IndividualProtocol
    from belgie_proto.core.oauth_account import OAuthAccountProtocol

    from belgie_oauth._config import OAuthProvider
    from belgie_oauth._helpers import OAuthTokenCodec
    from belgie_oauth._models import ResponseCookie
    from belgie_oauth._state import OAuthStateStore
    from belgie_oauth._transport import OAuthTransport
    from belgie_oauth._types import (
        JSONValue,
        OAuthAccountTokenUpdates,
        OAuthBelgieRuntime,
        OAuthFlowIntent,
        OAuthResponseMode,
    )


class IndividualProfileUpdates(TypedDict, total=False):
    name: str
    image: str
    email_verified_at: datetime


class OAuthFlowCoordinator:
    def __init__(
        self,
        *,
        config: OAuthProvider,
        provider_id: str,
        transport: OAuthTransport,
        state_store: OAuthStateStore,
        token_codec: OAuthTokenCodec,
    ) -> None:
        self.config = config
        self.provider_id = provider_id
        self.transport = transport
        self.state_store = state_store
        self.token_codec = token_codec

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
    ) -> tuple[str, list[ResponseCookie]]:
        state = generate_state_token()
        code_verifier = generate_code_verifier() if self.config.use_pkce else None
        nonce = generate_state_token() if self.transport.should_use_nonce(scopes) else None
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        oauth_state = PendingOAuthState(
            state=state,
            provider=self.provider_id,
            individual_id=individual_id,
            code_verifier=code_verifier,
            nonce=nonce,
            intent=intent,
            redirect_url=redirect_url,
            error_redirect_url=error_redirect_url,
            new_user_redirect_url=new_user_redirect_url,
            payload=payload,
            request_sign_up=request_sign_up,
            expires_at=expires_at,
        )
        cookies = await self.state_store.create_authorization_state(client, oauth_state)
        authorization_url = await self.transport.generate_authorization_url(
            state,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
            code_verifier=code_verifier,
            nonce=nonce,
        )
        return authorization_url, cookies

    async def token_set(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthTokenSet:
        account = await self._get_linked_account(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )
        if account is None:
            msg = "oauth account not found"
            raise OAuthError(msg)
        if auto_refresh and self._should_refresh(account):
            account = await self.refresh_account(
                client,
                individual_id=individual_id,
                provider_account_id=provider_account_id,
            )
        if account.access_token is None:
            msg = "oauth account does not have an access token"
            raise OAuthError(msg)
        return OAuthTokenSet.from_account(account)

    async def list_accounts(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
    ) -> list[OAuthLinkedAccount]:
        accounts = await client.list_oauth_accounts(individual_id=individual_id, provider=self.provider_id)
        return [self._linked_account_snapshot(account) for account in accounts]

    async def refresh_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> OAuthLinkedAccount:
        record = await client.get_oauth_account_for_individual(
            individual_id=individual_id,
            provider=self.provider_id,
            provider_account_id=provider_account_id,
        )
        if record is None:
            msg = "oauth account not found"
            raise OAuthError(msg)

        account = self._linked_account_snapshot(record)
        if account.refresh_token is None:
            msg = "oauth account does not have a refresh token"
            raise OAuthError(msg)

        refreshed = await self.transport.refresh_token_set(OAuthTokenSet.from_account(account))
        updated = await client.update_oauth_account_by_id(record.id, **self._encoded_token_updates(refreshed))
        if updated is None:
            msg = "failed to update refreshed oauth account"
            raise OAuthError(msg)
        return self._linked_account_snapshot(updated)

    async def account_info(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthUserInfo | None:
        try:
            token_set = await self.token_set(
                client,
                individual_id=individual_id,
                provider_account_id=provider_account_id,
                auto_refresh=auto_refresh,
            )
        except OAuthError:
            return None
        return await self.transport.fetch_provider_profile(token_set)

    async def unlink_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> bool:
        return await client.unlink_oauth_account(
            individual_id=individual_id,
            provider=self.provider_id,
            provider_account_id=provider_account_id,
        )

    async def complete_callback(  # noqa: C901, PLR0912
        self,
        *,
        belgie: OAuthBelgieRuntime,
        client: BelgieClient,
        request: Request,
    ) -> RedirectResponse:
        consumed_state: ConsumedOAuthState | None = None
        try:
            normalization = await self.normalize_form_post_callback(request)
            if normalization is not None:
                return normalization

            callback_params = await self.extract_callback_params(request)
            if not (state := callback_params.get("state")):
                raise OAuthCallbackError("state_mismatch", "missing OAuth state")

            consumed_state = await self.state_store.consume_callback_state(client, request, state)
            if consumed_state.provider and consumed_state.provider != self.provider_id:
                raise OAuthCallbackError("state_mismatch", "OAuth state provider mismatch")

            metadata = await self.transport.resolve_server_metadata()
            self.transport.validate_issuer_parameter(callback_params.get("iss"), metadata)

            request.state.oauth_state = consumed_state
            request.state.oauth_payload = consumed_state.payload

            if callback_params.get("error"):
                description = callback_params.get("error_description") or callback_params["error"]
                raise OAuthCallbackError(str(callback_params["error"]), description)

            if not (code := callback_params.get("code")):
                raise OAuthCallbackError("oauth_code_verification_failed", "missing OAuth authorization code")

            try:
                token_set = await self.transport.exchange_code_for_tokens(
                    code,
                    code_verifier=consumed_state.code_verifier,
                )
            except OAuthError as exc:
                if isinstance(exc, OAuthCallbackError):
                    raise
                raise OAuthCallbackError("oauth_code_verification_failed", str(exc)) from exc
            try:
                provider_user = await self.transport.fetch_provider_profile(
                    token_set,
                    nonce=consumed_state.nonce,
                )
            except OAuthError as exc:
                if isinstance(exc, OAuthCallbackError):
                    raise
                raise OAuthCallbackError("user_info_missing", str(exc)) from exc

            if consumed_state.intent == "link":
                response = await self._complete_link_flow(
                    belgie=belgie,
                    client=client,
                    oauth_state=consumed_state,
                    provider_user=provider_user,
                    token_set=token_set,
                )
            else:
                response = await self._complete_signin_flow(
                    belgie=belgie,
                    client=client,
                    request=request,
                    oauth_state=consumed_state,
                    provider_user=provider_user,
                    token_set=token_set,
                )
            self.state_store.clear_cookies(response)
            return response  # noqa: TRY300
        except OAuthError as exc:
            if consumed_state and consumed_state.error_redirect_url:
                response = RedirectResponse(
                    url=append_query_params(
                        consumed_state.error_redirect_url,
                        {
                            "error": exc.code if isinstance(exc, OAuthCallbackError) else "oauth_callback_failed",
                        },
                    ),
                    status_code=status.HTTP_302_FOUND,
                )
                self.state_store.clear_cookies(response)
                return response
            raise

    async def normalize_form_post_callback(self, request: Request) -> RedirectResponse | None:
        if request.method.upper() != "POST" or self.state_store.has_callback_cookie(request):
            return None
        callback_params = await self.extract_callback_params(request)
        if not callback_params:
            return None
        parsed = urlparse(str(request.url))
        callback_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", parsed.fragment))
        return RedirectResponse(
            url=append_query_params(callback_url, callback_params),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    async def extract_callback_params(self, request: Request) -> dict[str, str]:
        params = dict(request.query_params)
        if request.method.upper() == "POST":
            form = await request.form()
            params.update({key: str(value) for key, value in form.items()})
        return params

    async def _complete_signin_flow(  # noqa: C901, PLR0912, PLR0913
        self,
        *,
        belgie: OAuthBelgieRuntime,
        client: BelgieClient,
        request: Request,
        oauth_state: ConsumedOAuthState,
        provider_user: OAuthUserInfo,
        token_set: OAuthTokenSet,
    ) -> RedirectResponse:
        existing_account = await client.get_oauth_account(
            provider=self.provider_id,
            provider_account_id=provider_user.provider_account_id,
        )

        if existing_account is not None:
            individual = await client.adapter.get_individual_by_id(client.db, existing_account.individual_id)
            if individual is None:
                msg = "linked individual not found"
                raise OAuthError(msg)
            individual = await self._refresh_individual_profile(client, individual, provider_user) or individual
            session = await client.sign_in_individual(individual, request=request)
            if self.config.update_account_on_sign_in:
                updated_account = await client.update_oauth_account_by_id(
                    existing_account.id,
                    **self._encoded_token_updates(token_set),
                )
                if updated_account is None:
                    msg = "failed to update linked oauth account"
                    raise OAuthError(msg)
            await belgie.after_authenticate(
                client=client,
                request=request,
                individual=individual,
                profile=AuthenticatedProfile(
                    provider=self.provider_id,
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

        existing_individual = await client.adapter.get_individual_by_email(client.db, provider_user.email)
        if existing_individual is not None:
            if not self.config.allow_implicit_account_linking:
                raise OAuthCallbackError("account_not_linked", "implicit account linking is disabled")
            if not (provider_user.email_verified or self.config.trusted_for_account_linking):
                raise OAuthCallbackError(
                    "account_not_linked",
                    "provider email is not trusted for implicit account linking",
                )
        elif self.config.disable_sign_up or (self.config.disable_implicit_sign_up and not oauth_state.request_sign_up):
            raise OAuthCallbackError("signup_disabled", "sign up is disabled for this provider")

        verified_at = datetime.now(UTC) if provider_user.email_verified else None
        individual, created = await client.get_or_create_individual(
            provider_user.email,
            name=provider_user.name,
            image=provider_user.image,
            email_verified_at=verified_at,
        )
        if not created:
            if not self.config.allow_implicit_account_linking:
                raise OAuthCallbackError("account_not_linked", "implicit account linking is disabled")
            if not (provider_user.email_verified or self.config.trusted_for_account_linking):
                raise OAuthCallbackError(
                    "account_not_linked",
                    "provider email is not trusted for implicit account linking",
                )
            individual = await self._refresh_individual_profile(client, individual, provider_user) or individual
        session = await client.sign_in_individual(individual, request=request)
        if created and client.after_sign_up is not None:
            await client.after_sign_up(
                client=client,
                request=request,
                individual=individual,
            )

        try:
            await client.upsert_oauth_account(
                individual_id=individual.id,
                provider=self.provider_id,
                provider_account_id=provider_user.provider_account_id,
                **self._encoded_token_updates(token_set),
            )
        except OAuthError as exc:
            if "already linked to another individual" in str(exc):
                raise OAuthCallbackError("account_already_linked_to_different_user", str(exc)) from exc
            raise
        await belgie.after_authenticate(
            client=client,
            request=request,
            individual=individual,
            profile=AuthenticatedProfile(
                provider=self.provider_id,
                provider_account_id=provider_user.provider_account_id,
                email=provider_user.email,
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

    async def _complete_link_flow(
        self,
        *,
        belgie: OAuthBelgieRuntime,
        client: BelgieClient,
        oauth_state: ConsumedOAuthState,
        provider_user: OAuthUserInfo,
        token_set: OAuthTokenSet,
    ) -> RedirectResponse:
        if oauth_state.individual_id is None:
            msg = "link flow is missing the initiating individual"
            raise OAuthError(msg)
        if (individual := await client.adapter.get_individual_by_id(client.db, oauth_state.individual_id)) is None:
            msg = "initiating individual not found"
            raise OAuthError(msg)

        if not self.config.allow_different_link_emails:
            if provider_user.email is None:
                raise OAuthCallbackError("email_missing", "provider user info missing email")
            if not self._emails_match(individual.email, provider_user.email):
                raise OAuthCallbackError(
                    "email_does_not_match",
                    "provider email does not match the initiating individual",
                )

        existing_account = await client.get_oauth_account(
            provider=self.provider_id,
            provider_account_id=provider_user.provider_account_id,
        )
        if existing_account is not None and existing_account.individual_id != oauth_state.individual_id:
            raise OAuthCallbackError(
                "account_already_linked_to_different_user",
                "oauth account already linked to another individual",
            )

        try:
            await client.upsert_oauth_account(
                individual_id=oauth_state.individual_id,
                provider=self.provider_id,
                provider_account_id=provider_user.provider_account_id,
                **self._encoded_token_updates(token_set),
            )
        except OAuthError as exc:
            if "already linked to another individual" in str(exc):
                raise OAuthCallbackError("account_already_linked_to_different_user", str(exc)) from exc
            raise
        await self._refresh_verified_email(
            client,
            individual_id=oauth_state.individual_id,
            individual_email=individual.email,
            provider_user=provider_user,
        )

        return RedirectResponse(
            url=oauth_state.redirect_url or belgie.settings.urls.signin_redirect,
            status_code=status.HTTP_302_FOUND,
        )

    async def _refresh_individual_profile(
        self,
        client: BelgieClient,
        individual: IndividualProtocol[str],
        provider_user: OAuthUserInfo,
    ) -> IndividualProtocol[str] | None:
        updates: IndividualProfileUpdates = {}
        if self.config.override_user_info_on_sign_in and provider_user.name is not None:
            updates["name"] = provider_user.name
        if self.config.override_user_info_on_sign_in and provider_user.image is not None:
            updates["image"] = provider_user.image
        if self._emails_match(individual.email, provider_user.email) and provider_user.email_verified:
            updates["email_verified_at"] = datetime.now(UTC)
        if not updates:
            return None
        return await client.adapter.update_individual(client.db, individual.id, **updates)

    async def _refresh_verified_email(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        individual_email: str | None,
        provider_user: OAuthUserInfo,
    ) -> None:
        if not self._emails_match(individual_email, provider_user.email) or not provider_user.email_verified:
            return
        await client.adapter.update_individual(
            client.db,
            individual_id,
            email_verified_at=datetime.now(UTC),
        )

    async def _get_linked_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> OAuthLinkedAccount | None:
        record = await client.get_oauth_account_for_individual(
            individual_id=individual_id,
            provider=self.provider_id,
            provider_account_id=provider_account_id,
        )
        if record is None:
            return None
        return self._linked_account_snapshot(record)

    def _encoded_token_updates(self, token_set: OAuthTokenSet) -> OAuthAccountTokenUpdates:
        return {
            "access_token": self.token_codec.encode(token_set.access_token),
            "refresh_token": self.token_codec.encode(token_set.refresh_token),
            "access_token_expires_at": token_set.access_token_expires_at,
            "refresh_token_expires_at": token_set.refresh_token_expires_at,
            "scope": token_set.scope,
            "token_type": token_set.token_type,
            "id_token": self.token_codec.encode(token_set.id_token),
        }

    def _linked_account_snapshot(self, account: OAuthAccountProtocol) -> OAuthLinkedAccount:
        return OAuthLinkedAccount.from_model(
            account,
            access_token=self.token_codec.decode(account.access_token),
            refresh_token=self.token_codec.decode(account.refresh_token),
            id_token=self.token_codec.decode(account.id_token),
        )

    def _should_refresh(self, account: OAuthLinkedAccount) -> bool:
        if account.access_token_expires_at is None or account.refresh_token is None:
            return False
        return account.access_token_expires_at <= datetime.now(UTC) + timedelta(seconds=30)

    def _emails_match(self, current_email: str | None, provider_email: str | None) -> bool:
        return (
            current_email is not None
            and provider_email is not None
            and current_email.casefold() == provider_email.casefold()
        )
