from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any

from belgie_core.core.hooks import HookContext
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import SecurityScopes
from pydantic import AnyHttpUrl, AnyUrl

from belgie_oauth.models import InvalidRedirectUriError, InvalidScopeError, OAuthMetadata
from belgie_oauth.provider import AuthorizationParams, SimpleOAuthProvider
from belgie_oauth.utils import create_code_challenge, join_url

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_core.core.client import BelgieClient

    from belgie_oauth.settings import OAuthSettings


def create_auth_router(  # noqa: C901, PLR0915
    belgie: Belgie,
    provider: SimpleOAuthProvider,
    settings: OAuthSettings,
    issuer_url: str,
) -> APIRouter:
    router = APIRouter(prefix=settings.route_prefix, tags=["oauth"])

    metadata = _build_metadata(issuer_url, settings)

    async def metadata_handler(_: Request) -> Response:
        return JSONResponse(metadata.model_dump(mode="json"))

    async def authorize_handler(  # noqa: C901
        request: Request,
        client: BelgieClient = Depends(belgie),  # noqa: B008
    ) -> Response:
        data = await _get_request_params(request)
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
        state = _get_str(data, "state") or secrets.token_hex(16)

        params = AuthorizationParams(
            state=state,
            scopes=scopes,
            code_challenge=code_challenge,
            redirect_uri=validated_redirect_uri,
            redirect_uri_provided_explicitly=redirect_uri_raw is not None,
            resource=resource,
        )

        login_url = await provider.authorize(oauth_client, params)

        try:
            await client.get_user(SecurityScopes(), request)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)
            raise

        try:
            redirect_url = await provider.issue_authorization_code(state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

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

    async def login_page_handler(request: Request) -> Response:
        state = request.query_params.get("state")
        if not state:
            raise HTTPException(status_code=400, detail="missing state")

        login_action = join_url(issuer_url, "login/callback")
        html = _build_login_page(
            login_action=login_action,
            state=state,
            username=settings.demo_username,
            password=settings.demo_password,
        )
        return HTMLResponse(content=html)

    async def login_callback_handler(
        request: Request,
        client: BelgieClient = Depends(belgie),  # noqa: B008
    ) -> Response:
        form = await request.form()
        username = _get_str(form, "username")
        password = _get_str(form, "password")
        state = _get_str(form, "state")

        if not username or not password or not state:
            raise HTTPException(status_code=400, detail="missing credentials")

        if username != settings.demo_username or password != settings.demo_password:
            raise HTTPException(status_code=401, detail="invalid credentials")

        user = await client.adapter.get_user_by_email(client.db, username)
        created = False
        if user is None:
            user = await client.adapter.create_user(client.db, email=username)
            created = True

        if created:
            async with client.hook_runner.dispatch("on_signup", HookContext(user=user, db=client.db)):
                pass

        session = await client.session_manager.create_session(client.db, user_id=user.id)

        async with client.hook_runner.dispatch("on_signin", HookContext(user=user, db=client.db)):
            pass

        try:
            redirect_url = await provider.issue_authorization_code(state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        cookie = belgie.settings.cookie
        response.set_cookie(
            key=cookie.name,
            value=str(session.id),
            max_age=belgie.settings.session.max_age,
            httponly=cookie.http_only,
            secure=cookie.secure,
            samesite=cookie.same_site,
            domain=cookie.domain,
        )
        return response

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
                "iat": int(time.time()),
                "token_type": "Bearer",
                "aud": access_token.resource,
            },
        )

    router.add_api_route(
        "/.well-known/oauth-authorization-server",
        metadata_handler,
        methods=["GET"],
    )
    router.add_api_route("/authorize", authorize_handler, methods=["GET", "POST"])
    router.add_api_route("/token", token_handler, methods=["POST"])
    router.add_api_route("/login", login_page_handler, methods=["GET"])
    router.add_api_route("/login/callback", login_callback_handler, methods=["POST"])
    router.add_api_route("/introspect", introspect_handler, methods=["POST"])

    return router


def _build_metadata(issuer_url: str, settings: OAuthSettings) -> OAuthMetadata:
    authorization_endpoint = AnyHttpUrl(join_url(issuer_url, "authorize"))
    token_endpoint = AnyHttpUrl(join_url(issuer_url, "token"))
    introspection_endpoint = AnyHttpUrl(join_url(issuer_url, "introspect"))

    return OAuthMetadata(
        issuer=AnyHttpUrl(issuer_url),
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        scopes_supported=[settings.default_scope],
        response_types_supported=["code"],
        grant_types_supported=["authorization_code"],
        token_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
        code_challenge_methods_supported=["S256"],
        introspection_endpoint=introspection_endpoint,
    )


def _build_login_page(*, login_action: str, state: str, username: str, password: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Belgie Demo Authentication</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; }}
        .form-group {{ margin-bottom: 15px; }}
        input {{ width: 100%; padding: 8px; margin-top: 5px; }}
        button {{ background-color: #4CAF50; color: white; padding: 10px 15px; border: none; cursor: pointer; }}
    </style>
</head>
<body>
    <h2>Belgie Demo Authentication</h2>
    <p>This is a simplified authentication demo. Use the demo credentials below:</p>
    <p><strong>Username:</strong> {username}<br>
    <strong>Password:</strong> {password}</p>

    <form action="{login_action}" method="post">
        <input type="hidden" name="state" value="{state}">
        <div class="form-group">
            <label>Username:</label>
            <input type="text" name="username" value="{username}" required>
        </div>
        <div class="form-group">
            <label>Password:</label>
            <input type="password" name="password" value="{password}" required>
        </div>
        <button type="submit">Sign In</button>
    </form>
</body>
</html>
"""


def _oauth_error(error: str, description: str | None = None, status_code: int = 400) -> JSONResponse:
    payload: dict[str, Any] = {"error": error}
    if description:
        payload["error_description"] = description
    return JSONResponse(payload, status_code=status_code)


async def _get_request_params(request: Request) -> dict[str, str]:
    if request.method == "GET":
        return dict(request.query_params)
    return dict(await request.form())


def _get_str(data, key: str) -> str | None:  # noqa: ANN001
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None
