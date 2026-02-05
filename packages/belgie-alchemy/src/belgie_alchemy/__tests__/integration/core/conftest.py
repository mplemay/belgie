import sys
from pathlib import Path
from typing import Annotated

import pytest
from belgie_core.core.belgie import Belgie
from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse

PACKAGES_ROOT = Path(__file__).resolve().parents[6]
OAUTH_CLIENT_SRC = PACKAGES_ROOT / "belgie-oauth" / "src"
if str(OAUTH_CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(OAUTH_CLIENT_SRC))

from belgie_oauth import GoogleOAuthClient, GoogleOAuthPlugin  # noqa: E402


@pytest.fixture
def add_google_login_route():
    def apply(app: FastAPI, auth: Belgie) -> None:
        google_plugin = next(plugin for plugin in auth.plugins if isinstance(plugin, GoogleOAuthPlugin))

        @app.get("/login/google")
        async def login_google(
            google: Annotated[GoogleOAuthClient, Depends(google_plugin)],
            return_to: str | None = None,
        ) -> RedirectResponse:
            auth_url = await google.signin_url(return_to=return_to)
            return RedirectResponse(url=auth_url, status_code=302)

    return apply
