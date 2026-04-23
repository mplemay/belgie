from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from belgie_proto.core.json import JSONValue
    from belgie_proto.sso import SAMLProviderConfig, SSOProviderProtocol
    from fastapi import Request


@dataclass(slots=True, kw_only=True, frozen=True)
class SAMLStartResult:
    redirect_url: str | None = None
    form_action: str | None = None
    form_fields: dict[str, str] = field(default_factory=dict)
    request_id: str | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class SAMLResponseProfile:
    provider_account_id: str
    email: str | None
    email_verified: bool
    name: str | None = None
    raw: dict[str, JSONValue] = field(default_factory=dict)
    session_index: str | None = None


@runtime_checkable
class SAMLEngine(Protocol):
    async def metadata_xml(
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        acs_url: str,
    ) -> str: ...

    async def start_signin(
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        acs_url: str,
        relay_state: str,
    ) -> SAMLStartResult: ...

    async def finish_signin(
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        request: Request,
        relay_state: str,
        request_id: str | None,
    ) -> SAMLResponseProfile: ...


class NullSAMLEngine:
    async def metadata_xml(
        self,
        *,
        provider: SSOProviderProtocol,  # noqa: ARG002
        config: SAMLProviderConfig,  # noqa: ARG002
        acs_url: str,  # noqa: ARG002
    ) -> str:
        msg = "SAML support is not configured"
        raise RuntimeError(msg)

    async def start_signin(
        self,
        *,
        provider: SSOProviderProtocol,  # noqa: ARG002
        config: SAMLProviderConfig,  # noqa: ARG002
        acs_url: str,  # noqa: ARG002
        relay_state: str,  # noqa: ARG002
    ) -> SAMLStartResult:
        msg = "SAML support is not configured"
        raise RuntimeError(msg)

    async def finish_signin(
        self,
        *,
        provider: SSOProviderProtocol,  # noqa: ARG002
        config: SAMLProviderConfig,  # noqa: ARG002
        request: Request,  # noqa: ARG002
        relay_state: str,  # noqa: ARG002
        request_id: str | None,  # noqa: ARG002
    ) -> SAMLResponseProfile:
        msg = "SAML support is not configured"
        raise RuntimeError(msg)
