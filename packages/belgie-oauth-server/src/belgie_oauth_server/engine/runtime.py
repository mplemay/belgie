from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from belgie_core.core.client import BelgieClient

    from belgie_oauth_server.provider import SimpleOAuthProvider
    from belgie_oauth_server.settings import OAuthServer


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthEngineRuntime:
    provider: SimpleOAuthProvider
    settings: OAuthServer
    belgie_client: BelgieClient
    belgie_base_url: str
    issuer_url: str
