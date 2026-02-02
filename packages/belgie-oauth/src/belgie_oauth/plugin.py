from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from belgie_core.core.protocols import Plugin

from belgie_oauth.provider import SimpleOAuthProvider
from belgie_oauth.routes import create_auth_router
from belgie_oauth.settings import OAuthSettings

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from fastapi import APIRouter


class OAuthPlugin(Plugin[OAuthSettings]):
    def __init__(self, belgie: Belgie, settings: OAuthSettings) -> None:
        self._belgie = belgie
        self._settings = settings

        issuer_url = str(settings.issuer_url) if settings.issuer_url else _build_issuer_url(belgie, settings)
        self._provider = SimpleOAuthProvider(settings, issuer_url=issuer_url)
        self._router = create_auth_router(
            belgie=belgie,
            provider=self._provider,
            settings=settings,
            issuer_url=issuer_url,
        )

    def router(self) -> APIRouter:
        return self._router


def _build_issuer_url(belgie: Belgie, settings: OAuthSettings) -> str:
    parsed = urlparse(belgie.settings.base_url)
    base_path = parsed.path.rstrip("/")
    prefix = settings.route_prefix.strip("/")
    auth_path = "auth"
    full_path = f"{base_path}/{auth_path}/{prefix}" if prefix else f"{base_path}/{auth_path}"
    return urlunparse(parsed._replace(path=full_path, query="", fragment=""))
