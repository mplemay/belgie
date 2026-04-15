from __future__ import annotations

from typing import Literal

type AuthorizationIntent = Literal["login", "create", "consent", "select_account", "post_login"]
type OAuthServerAudience = str | list[str]
type OAuthServerClientType = Literal["web", "native", "user-agent-based"]
type OAuthServerSubjectType = Literal["public", "pairwise"]
type TokenEndpointAuthMethod = Literal["none", "client_secret_post", "client_secret_basic"]
