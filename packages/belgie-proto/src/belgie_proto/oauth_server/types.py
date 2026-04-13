from __future__ import annotations

from typing import Literal

type AuthorizationIntent = Literal["login", "create", "consent", "select_account"]
type OAuthAudience = str | list[str]
type OAuthClientType = Literal["web", "native", "user-agent-based"]
type OAuthSubjectType = Literal["public", "pairwise"]
type TokenEndpointAuthMethod = Literal["none", "client_secret_post", "client_secret_basic"]
