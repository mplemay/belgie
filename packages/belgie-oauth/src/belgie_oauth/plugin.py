from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from belgie_core.core.protocols import Plugin

from belgie_oauth.provider import SimpleOAuthProvider
from belgie_oauth.routes import create_auth_router

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from fastapi import APIRouter

    from belgie_oauth.settings import OAuthSettings


class OAuthPlugin(Plugin):
    def __init__(self, settings: OAuthSettings) -> None:
        self._settings = settings

    def router(self, belgie: Belgie) -> APIRouter:
        issuer_url = (
            str(self._settings.issuer_url) if self._settings.issuer_url else _build_issuer_url(belgie, self._settings)
        )

        return create_auth_router(
            belgie=belgie,
            provider=SimpleOAuthProvider(self._settings, issuer_url=issuer_url),
            settings=self._settings,
            issuer_url=issuer_url,
        )


def _build_issuer_url(belgie: Belgie, settings: OAuthSettings) -> str:
    parsed = urlparse(belgie.settings.base_url)
    base_path = parsed.path.rstrip("/")
    prefix = settings.route_prefix.strip("/")
    auth_path = "auth"
    full_path = f"{base_path}/{auth_path}/{prefix}" if prefix else f"{base_path}/{auth_path}"
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))
