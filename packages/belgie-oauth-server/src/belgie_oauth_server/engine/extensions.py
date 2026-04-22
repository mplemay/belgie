from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from authlib.oauth2.rfc6749.errors import InvalidGrantError, InvalidRequestError
from authlib.oauth2.rfc7636.challenge import create_s256_code_challenge

from belgie_oauth_server.engine.bridge import run_async
from belgie_oauth_server.engine.helpers import parse_scope_param, pkce_requirement_for_client
from belgie_oauth_server.engine.token_generator import resolve_request_session_id
from belgie_oauth_server.engine.token_response import (
    apply_custom_token_response_fields,
    maybe_build_id_token,
)

if TYPE_CHECKING:
    from belgie_oauth_server.engine.authlib_server import BelgieAuthorizationServer
    from belgie_oauth_server.engine.models import AuthlibAuthorizationCode, AuthlibClient, AuthlibUser
    from belgie_oauth_server.engine.transport_starlette import StarletteOAuth2Request

_MIN_TOKEN_RESPONSE_ITEMS = 2


class BelgieCodeChallenge:
    def __call__(self, grant: object) -> None:
        grant.register_hook("after_validate_authorization_request_payload", self.validate_code_challenge)
        grant.register_hook("after_validate_token_request", self.validate_code_verifier)

    def validate_code_challenge(self, grant: object, _redirect_uri: str) -> None:
        request = cast("StarletteOAuth2Request", grant.request)
        client = cast("AuthlibClient", request.client)
        scopes = parse_scope_param(request.scope) or []

        challenge = request.payload.data.get("code_challenge")
        method = request.payload.data.get("code_challenge_method")
        pkce_requirement = pkce_requirement_for_client(client.record, scopes)
        if pkce_requirement is not None and not challenge:
            raise InvalidRequestError(pkce_requirement)

        if not challenge and not method:
            return
        if not challenge or not method:
            msg = "code_challenge and code_challenge_method must both be provided"
            raise InvalidRequestError(msg)
        if method != "S256":
            msg = "invalid code_challenge method, only S256 is supported"
            raise InvalidRequestError(msg)

    def validate_code_verifier(self, grant: object, _result: object) -> None:
        request = cast("StarletteOAuth2Request", grant.request)
        client = cast("AuthlibClient", request.client)
        authorization_code = cast("AuthlibAuthorizationCode", request.authorization_code)
        verifier = request.form.get("code_verifier")
        challenge = authorization_code.record.code_challenge
        pkce_requirement = pkce_requirement_for_client(client.record, authorization_code.record.scopes)

        if challenge is None and verifier:
            msg = "code_verifier provided but PKCE was not used in authorization"
            raise InvalidRequestError(msg)
        if challenge is None and pkce_requirement is not None:
            raise InvalidRequestError(pkce_requirement)
        if challenge is not None and not verifier:
            msg = "code_verifier required because PKCE was used in authorization"
            raise InvalidRequestError(msg)
        if challenge is None:
            return
        if create_s256_code_challenge(verifier) != challenge:
            msg = "invalid code_verifier"
            raise InvalidGrantError(msg)


class BelgieTokenResponseEnhancer:
    def __call__(self, grant: object) -> None:
        grant.register_hook("after_create_token_response", self.enhance_token_response)

    def enhance_token_response(self, grant: object, response: object) -> None:
        if not isinstance(response, tuple) or len(response) < _MIN_TOKEN_RESPONSE_ITEMS:
            return

        payload = response[1]
        if not isinstance(payload, dict):
            return

        server = cast("BelgieAuthorizationServer", grant.server)
        request = cast("StarletteOAuth2Request", grant.request)
        client = cast("AuthlibClient | None", request.client)
        if client is None:
            return

        scopes = parse_scope_param(payload.get("scope") if isinstance(payload.get("scope"), str) else None) or []
        user = cast("AuthlibUser | None", request.user)
        resolved_user = None
        if user is not None:
            try:
                resolved_user = run_async(
                    server.runtime.belgie_client.adapter.get_individual_by_id,
                    server.runtime.belgie_client.db,
                    UUID(user.get_user_id()),
                )
            except ValueError:
                resolved_user = None
        if "openid" in scopes and user is not None:
            payload["id_token"] = run_async(
                maybe_build_id_token,
                server.runtime.belgie_client,
                server.runtime.provider,
                server.runtime.settings,
                server.runtime.issuer_url,
                client.record,
                scopes=scopes,
                individual_id=user.get_user_id(),
                nonce=_resolve_request_nonce(request),
                session_id=resolve_request_session_id(request),
            )

        verification_value = None
        authorization_code = getattr(request, "authorization_code", None)
        if authorization_code is not None:
            verification_value = {
                "type": "authorization_code",
                "query": {
                    "client_id": client.get_client_id(),
                    "redirect_uri": authorization_code.record.redirect_uri,
                    "scope": " ".join(authorization_code.record.scopes),
                    "resource": authorization_code.record.resource,
                    "nonce": authorization_code.record.nonce,
                    "code_challenge": authorization_code.record.code_challenge,
                },
                "session_id": authorization_code.record.session_id,
                "user_id": authorization_code.record.individual_id,
                "reference_id": client.record.reference_id,
            }

        updated_payload = run_async(
            apply_custom_token_response_fields,
            server.runtime.settings,
            dict(payload),
            grant_type=grant.GRANT_TYPE,
            oauth_client=client.record,
            scopes=scopes,
            user=resolved_user,
            verification_value=verification_value,
        )
        payload.clear()
        payload.update(updated_payload.model_dump(mode="json", exclude_none=True))


def _resolve_request_nonce(request: StarletteOAuth2Request) -> str | None:
    authorization_code = getattr(request, "authorization_code", None)
    if authorization_code is None:
        return None
    return authorization_code.record.nonce
