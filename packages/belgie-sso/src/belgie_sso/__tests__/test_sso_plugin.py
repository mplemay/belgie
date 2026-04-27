# ruff: noqa: ARG002, ARG005, E501, EM101, TRY003

from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID, uuid4

import pytest
import xmlsec
from belgie_core.core.plugin import AuthenticatedProfile
from belgie_core.core.settings import BelgieSettings
from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo
from belgie_proto.sso import OIDCProviderConfig
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from lxml import etree as ET  # noqa: N812
from signxml import XMLSigner, methods
from signxml.algorithms import CanonicalizationMethod, DigestAlgorithm, SignatureMethod

from belgie_sso.__tests__.support import (
    FakeIndividual,
    FakeProvider,
    MemoryOrganizationAdapter,
    MemorySSOAdapter,
    build_domain,
    build_individual,
    build_organization,
    build_provider,
)
from belgie_sso.discovery import DiscoveryError
from belgie_sso.models import SSODomainChallenge, SSOProviderDetail
from belgie_sso.plugin import SSOPlugin
from belgie_sso.saml import SAMLResponseProfile, SAMLStartResult
from belgie_sso.settings import (
    DefaultSSOProviderConfig,
    DomainVerificationSettings,
    EnterpriseSSO,
    SAMLSecuritySettings,
)


@dataclass(frozen=True, slots=True)
class _KeyMaterial:
    private_key: str
    certificate: str


def _build_key_material(common_name: str, *, key_type: str = "rsa") -> _KeyMaterial:
    if key_type == "rsa":
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif key_type == "ec":
        private_key = ec.generate_private_key(ec.SECP256R1())
    else:
        raise ValueError(key_type)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=365))
        .sign(private_key, hashes.SHA256())
    )
    return _KeyMaterial(
        private_key=private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8"),
        certificate=certificate.public_bytes(serialization.Encoding.PEM).decode("utf-8"),
    )


_IDP_KEYS = _build_key_material("idp.example.com")
_SP_KEYS = _build_key_material("sp.example.com")
_SIGNATURE_METHODS = {
    "rsa-sha256": SignatureMethod.RSA_SHA256,
    "rsa-sha384": SignatureMethod.RSA_SHA384,
    "rsa-sha512": SignatureMethod.RSA_SHA512,
    "ecdsa-sha256": SignatureMethod.ECDSA_SHA256,
    "ecdsa-sha384": SignatureMethod.ECDSA_SHA384,
    "ecdsa-sha512": SignatureMethod.ECDSA_SHA512,
}
_DIGEST_METHODS = {
    "sha256": DigestAlgorithm.SHA256,
    "sha384": DigestAlgorithm.SHA384,
    "sha512": DigestAlgorithm.SHA512,
}
_SIGNATURE_URIS = {
    "rsa-sha256": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
    "rsa-sha384": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha384",
    "rsa-sha512": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha512",
    "ecdsa-sha256": "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256",
    "ecdsa-sha384": "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha384",
    "ecdsa-sha512": "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha512",
}
_DIGEST_URIS = {
    "sha256": "http://www.w3.org/2001/04/xmlenc#sha256",
    "sha384": "http://www.w3.org/2001/04/xmldsig-more#sha384",
    "sha512": "http://www.w3.org/2001/04/xmlenc#sha512",
}


def _sign_element(
    element: ET._Element,
    *,
    key_material: _KeyMaterial,
    signature_algorithm: str = "rsa-sha256",
    digest_algorithm: str = "sha256",
) -> ET._Element:
    return XMLSigner(
        method=methods.enveloped,
        signature_algorithm=_SIGNATURE_METHODS[signature_algorithm],
        digest_algorithm=_DIGEST_METHODS[digest_algorithm],
        c14n_algorithm=CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0,
    ).sign(
        element,
        key=key_material.private_key.encode("utf-8"),
        cert=key_material.certificate,
        reference_uri=f"#{element.attrib['ID']}",
        id_attribute="ID",
        always_add_key_value=False,
    )


def _hash_algorithm(signature_algorithm: str) -> hashes.HashAlgorithm:
    if signature_algorithm in {"rsa-sha256", "ecdsa-sha256"}:
        return hashes.SHA256()
    if signature_algorithm in {"rsa-sha384", "ecdsa-sha384"}:
        return hashes.SHA384()
    if signature_algorithm in {"rsa-sha512", "ecdsa-sha512"}:
        return hashes.SHA512()
    raise ValueError(signature_algorithm)


def _raw_query_value(url: str, key: str) -> str | None:
    query = urlparse(url).query
    for item in query.split("&"):
        if item == key:
            return ""
        if item.startswith(f"{key}="):
            return item.partition("=")[2]
    return None


def _decode_redirect_xml(url: str, *, payload_key: str) -> ET._Element:
    payload = _raw_query_value(url, payload_key)
    assert payload is not None
    compressed = base64.b64decode(unquote(payload))
    xml_bytes = zlib.decompress(compressed, wbits=-15)
    return ET.fromstring(xml_bytes)


def _assert_redirect_signature(url: str, *, payload_key: str, key_material: _KeyMaterial) -> None:
    payload = _raw_query_value(url, payload_key)
    sig_alg = _raw_query_value(url, "SigAlg")
    signature = _raw_query_value(url, "Signature")
    assert payload is not None
    assert sig_alg is not None
    assert signature is not None
    signed_parts = [f"{payload_key}={payload}"]
    if relay_state := _raw_query_value(url, "RelayState"):
        signed_parts.append(f"RelayState={relay_state}")
    signed_parts.append(f"SigAlg={sig_alg}")
    certificate = x509.load_pem_x509_certificate(key_material.certificate.encode("utf-8"))
    signature_algorithm = next(name for name, uri in _SIGNATURE_URIS.items() if uri == unquote(sig_alg))
    decoded_signature = base64.b64decode(unquote(signature))
    if signature_algorithm.startswith("rsa-"):
        certificate.public_key().verify(
            decoded_signature,
            "&".join(signed_parts).encode("utf-8"),
            padding.PKCS1v15(),
            _hash_algorithm(signature_algorithm),
        )
    else:
        certificate.public_key().verify(
            decoded_signature,
            "&".join(signed_parts).encode("utf-8"),
            ec.ECDSA(_hash_algorithm(signature_algorithm)),
        )


class DummyBelgie:
    def __init__(self, client: object) -> None:
        self._client = client
        self.plugins: list[object] = []
        self.settings = SimpleNamespace(
            base_url="http://localhost:8000",
            urls=SimpleNamespace(signin_redirect="/dashboard", signout_redirect="/signed-out"),
            cookie=SimpleNamespace(name="session", domain=None),
        )

    async def __call__(self) -> object:
        return self._client

    async def after_authenticate(
        self,
        *,
        client: object,
        request: object,
        individual: object,
        profile: object,
    ) -> None:
        return None

    async def sign_out(self, _db: object, session_id: UUID) -> bool:
        return await self._client.sign_out(session_id)


class FakeAdapter:
    def __init__(self) -> None:
        self.oauth_states: dict[str, SimpleNamespace] = {}
        self.individuals_by_email: dict[str, FakeIndividual] = {}
        self.individuals_by_id: dict[UUID, FakeIndividual] = {}
        self.oauth_accounts: dict[tuple[str, str], SimpleNamespace] = {}

    async def create_oauth_state(self, _db: object, *, state: str, expires_at: datetime, **kwargs: object) -> object:
        payload = {
            "state": state,
            "expires_at": expires_at,
            "provider": kwargs.get("provider"),
            "individual_id": kwargs.get("individual_id"),
            "code_verifier": kwargs.get("code_verifier"),
            "nonce": kwargs.get("nonce"),
            "intent": kwargs.get("intent", "signin"),
            "redirect_url": kwargs.get("redirect_url"),
            "error_redirect_url": kwargs.get("error_redirect_url"),
            "new_user_redirect_url": kwargs.get("new_user_redirect_url"),
            "payload": kwargs.get("payload"),
            "request_sign_up": kwargs.get("request_sign_up", False),
        }
        self.oauth_states[state] = SimpleNamespace(**payload)
        return self.oauth_states[state]

    async def get_oauth_state(self, _db: object, state: str) -> object | None:
        return self.oauth_states.get(state)

    async def delete_oauth_state(self, _db: object, state: str) -> bool:
        return self.oauth_states.pop(state, None) is not None

    async def get_individual_by_id(self, _db: object, individual_id: UUID) -> FakeIndividual | None:
        return self.individuals_by_id.get(individual_id)

    async def get_individual_by_email(self, _db: object, email: str) -> FakeIndividual | None:
        return self.individuals_by_email.get(email)

    async def update_individual(self, _db: object, individual_id: UUID, **updates: object) -> FakeIndividual | None:
        individual = self.individuals_by_id.get(individual_id)
        if individual is None:
            return None
        for key, value in updates.items():
            setattr(individual, key, value)
        return individual


class FakeBelgieClient:
    def __init__(self) -> None:
        self.db = object()
        self.adapter = FakeAdapter()
        self.created_oauth_accounts: list[dict[str, object]] = []
        self.after_sign_up = None
        self.update_individual_calls: list[tuple[FakeIndividual, object | None, dict[str, object]]] = []
        self.sessions: dict[UUID, SimpleNamespace] = {}
        self.current_individual = build_individual()
        self.adapter.individuals_by_email[self.current_individual.email] = self.current_individual
        self.adapter.individuals_by_id[self.current_individual.id] = self.current_individual

    async def get_individual(self, security_scopes, request):
        return self.current_individual

    async def get_oauth_account(self, *, provider: str, provider_account_id: str):
        return self.adapter.oauth_accounts.get((provider, provider_account_id))

    async def get_or_create_individual(
        self,
        email: str,
        *,
        name: str | None = None,
        image: str | None = None,
        email_verified_at: datetime | None = None,
    ) -> tuple[FakeIndividual, bool]:
        if email in self.adapter.individuals_by_email:
            return self.adapter.individuals_by_email[email], False
        individual = build_individual(email=email, name=name)
        individual.email_verified_at = email_verified_at
        individual.image = image
        self.adapter.individuals_by_email[email] = individual
        self.adapter.individuals_by_id[individual.id] = individual
        return individual, True

    async def sign_in_individual(self, individual: FakeIndividual, *, request):
        session = SimpleNamespace(
            id=uuid4(),
            individual_id=individual.id,
            request=request,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self.sessions[session.id] = session
        return session

    async def upsert_oauth_account(self, **payload: object) -> object:
        account = SimpleNamespace(id=uuid4(), **payload)
        self.created_oauth_accounts.append(payload)
        self.adapter.oauth_accounts[(str(payload["provider"]), str(payload["provider_account_id"]))] = account
        return account

    async def update_oauth_account_by_id(self, oauth_account_id: UUID, **payload: object) -> object:
        return SimpleNamespace(id=oauth_account_id, **payload)

    async def update_individual(
        self,
        individual: FakeIndividual,
        *,
        request=None,
        **updates: object,
    ) -> FakeIndividual | None:
        self.update_individual_calls.append((individual, request, updates))
        return await self.adapter.update_individual(self.db, individual.id, **updates)

    def create_session_cookie(self, session: object, response):
        response.set_cookie("session", str(session.id))
        return response

    async def get_session(self, request):
        cookie = request.cookies.get("session")
        if cookie is None:
            raise RuntimeError("missing session cookie")
        return self.sessions[UUID(cookie)]

    async def sign_out(self, session_id: UUID) -> bool:
        return self.sessions.pop(session_id, None) is not None


class FakeOIDCTransport:
    def __init__(self, *, email: str = "person@dept.example.com") -> None:
        self.config = SimpleNamespace(use_pkce=True)
        self.email = email
        self.last_authorization_kwargs: dict[str, object] | None = None

    def should_use_nonce(self, scopes):
        return True

    async def generate_authorization_url(self, state: str, **kwargs: object) -> str:
        self.last_authorization_kwargs = kwargs
        return f"https://idp.example.com/authorize?state={state}"

    async def resolve_server_metadata(self) -> dict[str, str]:
        return {"issuer": "https://idp.example.com"}

    def validate_issuer_parameter(self, issuer: str | None, metadata: dict[str, str]) -> None:
        if issuer is not None and issuer != "https://idp.example.com":
            raise ValueError("issuer mismatch")

    async def exchange_code_for_tokens(self, code: str, *, code_verifier: str | None = None) -> OAuthTokenSet:
        return OAuthTokenSet(
            access_token=f"access-{code}",
            refresh_token="refresh-token",
            token_type="Bearer",
            scope="openid email profile",
            id_token="id-token",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token_expires_at=None,
            raw={"access_token": f"access-{code}", "refresh_token": "refresh-token"},
        )

    async def fetch_provider_profile(self, token_set: OAuthTokenSet, *, nonce: str | None = None) -> OAuthUserInfo:
        return OAuthUserInfo(
            provider_account_id="oidc-user-1",
            email=self.email,
            email_verified=True,
            name="Person Example",
            raw={"sub": "oidc-user-1", "email": self.email, "email_verified": True, "name": "Person Example"},
        )


class MappedOIDCTransport(FakeOIDCTransport):
    def __init__(self, *, plugin: SSOPlugin, provider: object, raw_profile: dict[str, object]) -> None:
        super().__init__(email=str(raw_profile.get("email", "person@dept.example.com")))
        self._map_profile = plugin._build_profile_mapper(plugin._provider_oidc_config(provider))
        self._raw_profile = dict(raw_profile)

    async def fetch_provider_profile(self, token_set: OAuthTokenSet, *, nonce: str | None = None) -> OAuthUserInfo:
        return self._map_profile(dict(self._raw_profile), token_set)


class FailingDiscoveryOIDCTransport(FakeOIDCTransport):
    def __init__(
        self,
        *,
        fail_on_generate: bool = False,
        fail_on_metadata: bool = False,
        fail_on_exchange: bool = False,
    ) -> None:
        super().__init__()
        self._fail_on_generate = fail_on_generate
        self._fail_on_metadata = fail_on_metadata
        self._fail_on_exchange = fail_on_exchange

    async def generate_authorization_url(self, state: str, **kwargs: object) -> str:
        if self._fail_on_generate:
            raise DiscoveryError("discovery_timeout", "Discovery request timed out")
        return await super().generate_authorization_url(state, **kwargs)

    async def resolve_server_metadata(self) -> dict[str, str]:
        if self._fail_on_metadata:
            raise DiscoveryError("discovery_invalid_json", "Discovery endpoint returned invalid JSON")
        return await super().resolve_server_metadata()

    async def exchange_code_for_tokens(self, code: str, *, code_verifier: str | None = None) -> OAuthTokenSet:
        if self._fail_on_exchange:
            raise DiscoveryError("discovery_not_found", "Discovery endpoint not found")
        return await super().exchange_code_for_tokens(code, code_verifier=code_verifier)


class FakeSAMLEngine:
    async def metadata_xml(self, *, provider, config, acs_url):
        return f'<EntityDescriptor entityID="{config.entity_id}"><AssertionConsumerService Location="{acs_url}"/></EntityDescriptor>'

    async def start_signin(self, *, provider, config, acs_url, relay_state):
        return SAMLStartResult(
            form_action=config.sso_url,
            form_fields={"RelayState": relay_state, "SAMLRequest": "request"},
            request_id="request-123",
        )

    async def finish_signin(self, *, provider, config, request, relay_state, request_id):
        return SAMLResponseProfile(
            provider_account_id="saml-user-1",
            email="person@example.com",
            email_verified=True,
            name="Saml Person",
            raw={"email": "person@example.com", "request_id": request_id, "relay_state": relay_state},
        )


class RelayStateOnlySAMLEngine(FakeSAMLEngine):
    def __init__(self) -> None:
        self.finish_called = False

    async def finish_signin(self, *, provider, config, request, relay_state, request_id):
        self.finish_called = True
        raise AssertionError("RelayState-only GET callbacks should not parse a SAML response")


class StubManagementSSOClient:
    def __init__(self) -> None:
        self.oidc_payload: dict[str, object] | None = None
        self.deleted_provider_id: str | None = None
        self.last_challenge: str | None = None
        self.last_verify: str | None = None
        self.detail = SSOProviderDetail(
            id=uuid4(),
            provider_id="acme",
            provider_type="oidc",
            issuer="https://idp.example.com",
            organization_id=None,
            created_by_individual_id=uuid4(),
            domain="example.com",
            domain_verified=False,
            callback_url="http://localhost:8000/auth/provider/sso/callback",
            domain_challenge=None,
            config={
                "client_id": "****1234",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
                "userinfo_endpoint": "https://idp.example.com/userinfo",
                "scopes": ["openid", "email", "profile", "offline_access"],
                "token_endpoint_auth_method": "client_secret_basic",
                "use_pkce": True,
                "override_user_info_on_sign_in": False,
                "claim_mapping": {
                    "subject": "sub",
                    "email": "email",
                    "email_verified": "email_verified",
                    "name": "name",
                    "image": "picture",
                    "extra_fields": {},
                },
            },
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    async def register_oidc_provider(self, **payload: object) -> FakeProvider:
        self.oidc_payload = payload
        self.detail = replace(
            self.detail,
            provider_id=str(payload["provider_id"]),
            issuer=str(payload["issuer"]),
            domain=str(payload.get("domain") or ""),
        )
        return FakeProvider(
            id=self.detail.id,
            organization_id=None,
            created_by_individual_id=self.detail.created_by_individual_id,
            provider_type="oidc",
            provider_id=str(payload["provider_id"]),
            issuer=str(payload["issuer"]),
            domain=str(payload.get("domain") or ""),
            domain_verified=False,
            domain_verification_token=None,
            domain_verification_token_expires_at=None,
            oidc_config=None,
            saml_config=None,
            created_at=self.detail.created_at,
            updated_at=self.detail.updated_at,
        )

    async def get_provider_detail(self, *, provider_id: str) -> SSOProviderDetail:
        return self.detail

    async def list_provider_details(self, *, organization_id: UUID | None = None) -> list[SSOProviderDetail]:
        return [self.detail]

    async def delete_provider(self, *, provider_id: str) -> bool:
        self.deleted_provider_id = provider_id
        return True

    async def create_domain_challenge(self, *, provider_id: str) -> SSODomainChallenge:
        self.last_challenge = provider_id
        return SSODomainChallenge(
            domain="example.com",
            record_name="_belgie-sso-acme.example.com",
            record_value="_belgie-sso-acme=token",
            verification_token="token",
            expires_at=datetime.now(UTC) + timedelta(days=7),
            verified_at=None,
        )

    async def verify_domain(self, *, provider_id: str) -> FakeProvider:
        self.last_verify = provider_id
        self.detail = replace(self.detail, domain_verified=True, domain_challenge=None)
        return FakeProvider(
            id=self.detail.id,
            organization_id=None,
            created_by_individual_id=self.detail.created_by_individual_id,
            provider_type="oidc",
            provider_id=provider_id,
            issuer=self.detail.issuer,
            domain=self.detail.domain,
            domain_verified=True,
            domain_verification_token=None,
            domain_verification_token_expires_at=None,
            oidc_config=None,
            saml_config=None,
            created_at=self.detail.created_at,
            updated_at=self.detail.updated_at,
        )


def build_plugin(
    *,
    include_saml: bool = False,
    default_sso: str | None = None,
    default_providers: tuple[DefaultSSOProviderConfig, ...] = (),
    domain_verification_enabled: bool = False,
    verified_domain: bool = True,
    include_second_org_provider: bool = False,
    trusted_providers: tuple[str, ...] = (),
    redirect_uri: str | None = None,
    disable_sign_up: bool = False,
    disable_implicit_sign_up: bool = False,
    provision_user: object | None = None,
    provision_user_on_every_login: bool = False,
    organization_role_resolver: object | None = None,
    saml_engine: object | None = None,
    use_builtin_saml_engine: bool = False,
    saml_config_overrides: dict[str, object] | None = None,
    saml_settings: SAMLSecuritySettings | None = None,
) -> tuple[SSOPlugin, FakeBelgieClient, MemoryOrganizationAdapter]:
    organization = build_organization(slug="acme")
    providers = [
        build_provider(
            organization_id=organization.id,
            provider_id="acme",
            oidc_config={
                "issuer": "https://idp.example.com",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
                "userinfo_endpoint": "https://idp.example.com/userinfo",
                "scopes": ["openid", "email", "profile"],
                "token_endpoint_auth_method": "client_secret_basic",
                "use_pkce": True,
                "override_user_info_on_sign_in": False,
                "claim_mapping": {
                    "subject": "sub",
                    "email": "email",
                    "email_verified": "email_verified",
                    "name": "name",
                    "image": "picture",
                },
            },
        ),
    ]
    if include_second_org_provider:
        providers.append(
            build_provider(
                organization_id=organization.id,
                provider_id="backup",
                issuer="https://backup.example.com",
                oidc_config={
                    "issuer": "https://backup.example.com",
                    "client_id": "backup-client-id",
                    "client_secret": "backup-client-secret",
                    "authorization_endpoint": "https://backup.example.com/authorize",
                    "token_endpoint": "https://backup.example.com/token",
                    "userinfo_endpoint": "https://backup.example.com/userinfo",
                    "scopes": ["openid", "email", "profile"],
                    "token_endpoint_auth_method": "client_secret_basic",
                    "use_pkce": True,
                    "override_user_info_on_sign_in": False,
                    "claim_mapping": {
                        "subject": "sub",
                        "email": "email",
                        "email_verified": "email_verified",
                        "name": "name",
                        "image": "picture",
                    },
                },
            ),
        )
    if include_saml:
        saml_config = {
            "entity_id": "urn:acme:sp",
            "sso_url": "https://idp.example.com/saml",
            "x509_certificate": _IDP_KEYS.certificate,
            "slo_url": "https://idp.example.com/slo",
            "binding": "redirect",
            "allow_idp_initiated": True,
            "want_assertions_signed": True,
            "sign_authn_request": True,
            "signature_algorithm": "rsa-sha256",
            "digest_algorithm": "sha256",
            "private_key": _SP_KEYS.private_key,
            "signing_certificate": _SP_KEYS.certificate,
            "claim_mapping": {
                "subject": "name_id",
                "email": "email",
                "email_verified": "email_verified",
                "name": "name",
                "groups": "groups",
            },
        }
        if saml_config_overrides is not None:
            saml_config.update(saml_config_overrides)
        providers.append(
            build_provider(
                organization_id=organization.id,
                provider_type="saml",
                provider_id="acme-saml",
                saml_config=saml_config,
            ),
        )
    domain = build_domain(
        sso_provider_id=providers[0].id,
        verified_at=datetime.now(UTC) if verified_domain else None,
    )
    domain.verification_token_expires_at = datetime.now(UTC) + timedelta(days=7)
    domains = [domain]
    settings = EnterpriseSSO(
        adapter=MemorySSOAdapter(providers, domains),
        saml_engine=None if use_builtin_saml_engine else FakeSAMLEngine() if saml_engine is None else saml_engine,
        default_sso=default_sso,
        default_providers=default_providers,
        redirect_uri=redirect_uri,
        trusted_providers=trusted_providers,
        disable_sign_up=disable_sign_up,
        disable_implicit_sign_up=disable_implicit_sign_up,
        provision_user=provision_user,
        provision_user_on_every_login=provision_user_on_every_login,
        organization_role_resolver=organization_role_resolver,
        domain_verification=DomainVerificationSettings(enabled=domain_verification_enabled),
        trust_email_verified=use_builtin_saml_engine,
        saml=saml_settings or SAMLSecuritySettings(),
    )
    plugin = SSOPlugin(BelgieSettings(secret="secret", base_url="http://localhost:8000"), settings)
    organization_adapter = MemoryOrganizationAdapter(organization)
    plugin._organization_plugin_resolved = True
    plugin._organization_plugin = SimpleNamespace(settings=SimpleNamespace(adapter=organization_adapter))
    client_dependency = FakeBelgieClient()
    return plugin, client_dependency, organization_adapter


@pytest.mark.asyncio
async def test_refresh_individual_profile_uses_client_update_individual() -> None:
    plugin, client_dependency, _organization_adapter = build_plugin()
    provider = plugin._settings.adapter.providers["acme"]
    assert provider.oidc_config is not None
    provider.oidc_config["override_user_info_on_sign_in"] = True
    individual = client_dependency.current_individual
    individual.email = "person@example.com"
    individual.name = "Existing Person"
    individual.email_verified_at = None
    request = object()

    updated_individual = await plugin._refresh_individual_profile(
        client_dependency,
        request,
        provider,
        individual,
        OAuthUserInfo(
            provider_account_id="provider-account-1",
            email="person@example.com",
            email_verified=True,
            name="Updated Name",
            image="https://example.com/photo.jpg",
            raw={"sub": "provider-account-1"},
        ),
    )

    assert updated_individual is not None
    assert len(client_dependency.update_individual_calls) == 1
    call_individual, call_request, call_updates = client_dependency.update_individual_calls[0]
    assert call_individual is individual
    assert call_request is request
    assert call_updates["name"] == "Updated Name"
    assert call_updates["image"] == "https://example.com/photo.jpg"
    assert "email_verified_at" in call_updates


def _encode_xml(element: ET._Element) -> str:
    return base64.b64encode(ET.tostring(element, encoding="utf-8", xml_declaration=False)).decode("ascii")


def _certificate_body(certificate: str) -> str:
    return "".join(
        line.strip()
        for line in certificate.strip().splitlines()
        if "BEGIN CERTIFICATE" not in line and "END CERTIFICATE" not in line
    )


def _encrypt_assertion(response: ET._Element) -> None:
    assertion = next(child for child in response if child.tag == "Assertion")
    encrypted_data = xmlsec.template.encrypted_data_create(
        response,
        xmlsec.constants.TransformAes128Cbc,
        type=xmlsec.constants.TypeEncElement,
        ns="xenc",
    )
    xmlsec.template.encrypted_data_ensure_cipher_value(encrypted_data)
    key_info = xmlsec.template.encrypted_data_ensure_key_info(encrypted_data, ns="ds")
    encrypted_key = xmlsec.template.add_encrypted_key(key_info, xmlsec.constants.TransformRsaOaep)
    xmlsec.template.encrypted_data_ensure_cipher_value(encrypted_key)
    manager = xmlsec.KeysManager()
    manager.add_key(xmlsec.Key.from_memory(_SP_KEYS.certificate, xmlsec.constants.KeyDataFormatCertPem, None))
    context = xmlsec.EncryptionContext(manager)
    context.key = xmlsec.Key.generate(xmlsec.constants.KeyDataAes, 128, xmlsec.constants.KeyDataTypeSession)
    encrypted_data = context.encrypt_xml(encrypted_data, assertion)
    encrypted_assertion = ET.Element("EncryptedAssertion")
    encrypted_assertion.append(encrypted_data)
    response.append(encrypted_assertion)


def _build_saml_response_payload(  # noqa: C901, PLR0912
    *,
    recipient: str,
    issuer: str = "https://idp.example.com",
    in_response_to: str | None = None,
    assertion_id: str = "assertion-1",
    provider_account_id: str = "saml-user-1",
    email: str = "person@example.com",
    email_verified: str = "true",
    name: str = "Saml Person",
    session_index: str = "session-index-1",
    duplicate_assertion: bool = False,
    encrypt_assertion: bool = False,
    not_before: str = "2000-01-01T00:00:00Z",
    not_on_or_after: str = "2099-01-01T00:00:00Z",
    sign_assertion: bool = True,
    sign_response: bool = False,
    signature_algorithm: str | None = None,
    digest_algorithm: str | None = None,
    include_assertion: bool = True,
) -> str:
    response = ET.Element("Response", ID="response-1", Version="2.0", Destination=recipient)
    if in_response_to is not None:
        response.attrib["InResponseTo"] = in_response_to
    ET.SubElement(response, "Issuer").text = issuer
    status = ET.SubElement(response, "Status")
    ET.SubElement(
        status,
        "StatusCode",
        Value="urn:oasis:names:tc:SAML:2.0:status:Success",
    )
    if include_assertion:
        assertions = 2 if duplicate_assertion else 1
        for index in range(assertions):
            assertion = ET.Element("Assertion", ID=f"{assertion_id}-{index}" if duplicate_assertion else assertion_id)
            ET.SubElement(assertion, "Issuer").text = issuer
            subject = ET.SubElement(assertion, "Subject")
            ET.SubElement(subject, "NameID").text = provider_account_id
            subject_confirmation = ET.SubElement(subject, "SubjectConfirmation")
            subject_confirmation_data_attributes = {
                "Recipient": recipient,
                "NotOnOrAfter": not_on_or_after,
            }
            if in_response_to is not None:
                subject_confirmation_data_attributes["InResponseTo"] = in_response_to
            ET.SubElement(
                subject_confirmation,
                "SubjectConfirmationData",
                subject_confirmation_data_attributes,
            )
            ET.SubElement(
                assertion,
                "Conditions",
                {
                    "NotBefore": not_before,
                    "NotOnOrAfter": not_on_or_after,
                },
            )
            attribute_statement = ET.SubElement(assertion, "AttributeStatement")
            for attribute_name, attribute_value in {
                "email": email,
                "email_verified": email_verified,
                "name": name,
            }.items():
                attribute = ET.SubElement(attribute_statement, "Attribute", Name=attribute_name)
                ET.SubElement(attribute, "AttributeValue").text = attribute_value
            ET.SubElement(assertion, "AuthnStatement", SessionIndex=session_index)
            if sign_assertion:
                assertion = _sign_element(assertion, key_material=_IDP_KEYS)
            response.append(assertion)
        if encrypt_assertion:
            _encrypt_assertion(response)
    if sign_response:
        response = _sign_element(response, key_material=_IDP_KEYS)
    if signature_algorithm is not None:
        for element in response.iter():
            if element.tag.endswith("SignatureMethod"):
                element.attrib["Algorithm"] = signature_algorithm
    if digest_algorithm is not None:
        for element in response.iter():
            if element.tag.endswith("DigestMethod"):
                element.attrib["Algorithm"] = digest_algorithm
    return _encode_xml(response)


def _build_logout_request_payload(
    *,
    issuer: str = "https://idp.example.com",
    provider_account_id: str = "saml-user-1",
    session_index: str = "session-index-1",
    sign_message: bool = True,
) -> str:
    logout_request = ET.Element("LogoutRequest", ID="logout-request-1", Version="2.0")
    ET.SubElement(logout_request, "Issuer").text = issuer
    ET.SubElement(logout_request, "NameID").text = provider_account_id
    ET.SubElement(logout_request, "SessionIndex").text = session_index
    if sign_message:
        logout_request = _sign_element(logout_request, key_material=_IDP_KEYS)
    return _encode_xml(logout_request)


def _build_logout_response_payload(
    *,
    in_response_to: str,
    issuer: str = "https://idp.example.com",
    sign_message: bool = True,
) -> str:
    logout_response = ET.Element("LogoutResponse", ID="logout-response-1", Version="2.0", InResponseTo=in_response_to)
    ET.SubElement(logout_response, "Issuer").text = issuer
    status = ET.SubElement(logout_response, "Status")
    ET.SubElement(
        status,
        "StatusCode",
        Value="urn:oasis:names:tc:SAML:2.0:status:Success",
    )
    if sign_message:
        logout_response = _sign_element(logout_response, key_material=_IDP_KEYS)
    return _encode_xml(logout_response)


def test_router_no_longer_requires_organization_plugin() -> None:
    plugin, client_dependency, _ = build_plugin()
    plugin._organization_plugin_resolved = True
    plugin._organization_plugin = None
    belgie = DummyBelgie(client_dependency)

    router = plugin.router(belgie)

    assert router is not None


def test_signin_redirects_using_verified_domain_suffix_lookup(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?email=person@dept.example.com", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")


def test_signin_uses_default_sso_when_no_identifier_provided(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(default_sso="acme")
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")


def test_signin_uses_static_default_sso_when_no_identifier_provided(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        default_sso="static-default",
        default_providers=(
            DefaultSSOProviderConfig(
                domain="static.example.com",
                provider_id="static-default",
                issuer="https://static.example.com",
                oidc_config=OIDCProviderConfig(
                    issuer="https://static.example.com",
                    client_id="static-client-id",
                    client_secret="static-client-secret",
                    authorization_endpoint="https://static.example.com/authorize",
                    token_endpoint="https://static.example.com/token",
                    userinfo_endpoint="https://static.example.com/userinfo",
                    jwks_uri="https://static.example.com/jwks",
                ),
            ),
        ),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert client_dependency.adapter.oauth_states[state].payload["provider_id"] == "static-default"


def test_signin_prefers_default_sso_for_multi_provider_org(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(default_sso="backup", include_second_org_provider=True)
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?organization_slug=acme", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")


def test_signin_prefers_static_default_provider_by_domain(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        default_providers=(
            DefaultSSOProviderConfig(
                domain="static.example.com",
                provider_id="static-default",
                issuer="https://static.example.com",
                oidc_config=OIDCProviderConfig(
                    issuer="https://static.example.com",
                    client_id="static-client-id",
                    client_secret="static-client-secret",
                    authorization_endpoint="https://static.example.com/authorize",
                    token_endpoint="https://static.example.com/token",
                    userinfo_endpoint="https://static.example.com/userinfo",
                    jwks_uri="https://static.example.com/jwks",
                ),
            ),
        ),
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?email=person@static.example.com", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert client_dependency.adapter.oauth_states[state].payload["provider_id"] == "static-default"


def test_signin_passes_explicit_login_hint(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    transport = FakeOIDCTransport()
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: transport)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get(
        "/auth/provider/sso/signin?provider_id=acme&login_hint=person%40example.com",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert transport.last_authorization_kwargs is not None
    assert transport.last_authorization_kwargs["authorization_params"] == {"login_hint": "person@example.com"}


def test_signin_explicit_provider_id_uses_database_provider_when_default_provider_is_unrelated(monkeypatch) -> None:
    selected_provider_ids: list[str] = []
    plugin, client_dependency, _ = build_plugin(
        default_providers=(
            DefaultSSOProviderConfig(
                domain="static.example.com",
                provider_id="static-default",
                issuer="https://static.example.com",
                oidc_config=OIDCProviderConfig(
                    issuer="https://static.example.com",
                    client_id="static-client-id",
                    client_secret="static-client-secret",
                    authorization_endpoint="https://static.example.com/authorize",
                    token_endpoint="https://static.example.com/token",
                    userinfo_endpoint="https://static.example.com/userinfo",
                    jwks_uri="https://static.example.com/jwks",
                ),
            ),
        ),
    )
    belgie = DummyBelgie(client_dependency)

    def build_transport(provider: object) -> FakeOIDCTransport:
        selected_provider_ids.append(provider.provider_id)
        return FakeOIDCTransport()

    monkeypatch.setattr(plugin, "_build_oidc_transport", build_transport)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)

    assert response.status_code == 302
    assert selected_provider_ids == ["acme"]


def test_signin_unknown_provider_id_still_returns_404_when_default_providers_exist() -> None:
    plugin, client_dependency, _ = build_plugin(
        default_providers=(
            DefaultSSOProviderConfig(
                domain="static.example.com",
                provider_id="static-default",
                issuer="https://static.example.com",
                oidc_config=OIDCProviderConfig(
                    issuer="https://static.example.com",
                    client_id="static-client-id",
                    client_secret="static-client-secret",
                    authorization_endpoint="https://static.example.com/authorize",
                    token_endpoint="https://static.example.com/token",
                    userinfo_endpoint="https://static.example.com/userinfo",
                    jwks_uri="https://static.example.com/jwks",
                ),
            ),
        ),
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?provider_id=missing", follow_redirects=False)

    assert response.status_code == 404
    assert response.json()["detail"] == "provider not found"


def test_build_oidc_transport_resolves_relative_redirect_uri() -> None:
    plugin, _, _ = build_plugin(redirect_uri="/sso/callback")
    provider = plugin.settings.adapter.providers["acme"]

    transport = plugin._build_oidc_transport(provider)

    assert transport.redirect_uri == "http://localhost:8000/sso/callback"


def test_build_profile_mapper_preserves_raw_claims_and_adds_extra_field_aliases() -> None:
    plugin, _, _ = build_plugin()
    provider = plugin.settings.adapter.providers["acme"]
    assert provider.oidc_config is not None
    provider.oidc_config["claim_mapping"]["extra_fields"] = {
        "department_alias": "department",
        "tenant_alias": "tid",
    }
    mapper = plugin._build_profile_mapper(plugin._provider_oidc_config(provider))

    provider_user = mapper(
        {
            "sub": "oidc-user-1",
            "email": "person@example.com",
            "email_verified": True,
            "name": "Person Example",
            "department": "engineering",
            "tid": "tenant-123",
        },
        OAuthTokenSet(
            access_token="access-token",
            refresh_token=None,
            token_type="Bearer",
            scope="openid email profile",
            id_token="id-token",
            access_token_expires_at=None,
            refresh_token_expires_at=None,
            raw={"access_token": "access-token"},
        ),
    )

    assert provider_user.raw["department"] == "engineering"
    assert provider_user.raw["department_alias"] == "engineering"
    assert provider_user.raw["tid"] == "tenant-123"
    assert provider_user.raw["tenant_alias"] == "tenant-123"


def test_shared_callback_passes_mapped_oidc_extra_fields_to_provision_user(monkeypatch) -> None:
    captured_profiles: list[dict[str, object]] = []

    def provision_user(individual: object, context: object) -> None:
        _ = individual
        captured_profiles.append(dict(context.profile))

    plugin, client_dependency, _ = build_plugin(provision_user=provision_user)
    belgie = DummyBelgie(client_dependency)
    provider = plugin.settings.adapter.providers["acme"]
    assert provider.oidc_config is not None
    provider.oidc_config["claim_mapping"]["extra_fields"] = {
        "department_alias": "department",
        "tenant_alias": "tid",
    }
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda resolved_provider: MappedOIDCTransport(
            plugin=plugin,
            provider=resolved_provider,
            raw_profile={
                "sub": "oidc-user-1",
                "email": "person@dept.example.com",
                "email_verified": True,
                "name": "Person Example",
                "department": "engineering",
                "tid": "tenant-123",
            },
        ),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme&request_sign_up=true", follow_redirects=False)
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert captured_profiles == [
        {
            "sub": "oidc-user-1",
            "email": "person@dept.example.com",
            "email_verified": True,
            "name": "Person Example",
            "department": "engineering",
            "tid": "tenant-123",
            "department_alias": "engineering",
            "tenant_alias": "tenant-123",
        },
    ]


def test_shared_callback_passes_mapped_oidc_extra_fields_to_role_resolver(monkeypatch) -> None:
    def organization_role_resolver(context: object) -> str:
        return "admin" if context.profile["department_alias"] == "engineering" else "member"

    plugin, client_dependency, organization_adapter = build_plugin(
        organization_role_resolver=organization_role_resolver,
    )
    belgie = DummyBelgie(client_dependency)
    provider = plugin.settings.adapter.providers["acme"]
    assert provider.oidc_config is not None
    provider.oidc_config["claim_mapping"]["extra_fields"] = {"department_alias": "department"}
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda resolved_provider: MappedOIDCTransport(
            plugin=plugin,
            provider=resolved_provider,
            raw_profile={
                "sub": "oidc-user-1",
                "email": "person@dept.example.com",
                "email_verified": True,
                "name": "Person Example",
                "department": "engineering",
            },
        ),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme&request_sign_up=true", follow_redirects=False)
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert organization_adapter.created_members[-1][2] == "admin"


def test_shared_callback_creates_session_and_assigns_org(monkeypatch) -> None:
    plugin, client_dependency, organization_adapter = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?email=person@dept.example.com&redirect_to=%2Fafter",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/after"
    assert len(client_dependency.created_oauth_accounts) == 1
    assert organization_adapter.created_members


def test_callback_redirects_to_error_target_when_email_not_trusted(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FakeOIDCTransport(email="person@untrusted.com"),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?provider_id=acme&error_redirect_url=%2Ferror",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/error?error=signup_disabled")


def test_callback_falls_back_to_redirect_target_when_error_redirect_is_missing(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FakeOIDCTransport(email="person@untrusted.com"),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?provider_id=acme&redirect_to=%2Fafter",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/after?error=signup_disabled")


def test_signin_redirects_to_error_target_when_oidc_discovery_fails(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FailingDiscoveryOIDCTransport(fail_on_generate=True),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get(
        "/auth/provider/sso/signin?provider_id=acme&error_redirect_url=%2Ferror",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/error?error=discovery_failed")
    assert "error_description=Discovery+request+timed+out" in response.headers["location"]
    assert client_dependency.adapter.oauth_states == {}


def test_signin_returns_http_error_when_oidc_discovery_fails_without_redirect_target(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FailingDiscoveryOIDCTransport(fail_on_generate=True),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)

    assert response.status_code == 502
    assert response.json()["detail"] == "OIDC discovery failed: Discovery request timed out"


def test_callback_redirects_to_error_target_when_oidc_runtime_discovery_fails(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FailingDiscoveryOIDCTransport(fail_on_metadata=True),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?provider_id=acme&error_redirect_url=%2Ferror",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/error?error=discovery_failed")
    assert "error_description=Discovery+endpoint+returned+invalid+JSON" in response.headers["location"]


def test_callback_trusts_provider_in_trusted_providers(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(trusted_providers=("acme",))
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FakeOIDCTransport(email="person@untrusted.com"),
    )
    existing = FakeIndividual(
        id=uuid4(),
        email="person@untrusted.com",
        email_verified_at=None,
        name="Existing Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )
    client_dependency.adapter.individuals_by_email[existing.email] = existing
    client_dependency.adapter.individuals_by_id[existing.id] = existing

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert response.cookies.get("session") is not None


def test_callback_request_sign_up_allows_new_user_when_disable_implicit_sign_up_is_enabled(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(disable_implicit_sign_up=True)
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?provider_id=acme&request_sign_up=true&redirect_to=%2Fafter",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/after"
    assert len(client_dependency.created_oauth_accounts) == 1


def test_callback_ignores_protocol_relative_redirect_target(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?provider_id=acme&request_sign_up=true&redirect_to=%2F%2Fevil.example.com",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


def test_callback_falls_back_to_redirect_target_when_error_redirect_is_rejected(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FakeOIDCTransport(email="person@untrusted.com"),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        "/auth/provider/sso/signin?provider_id=acme&redirect_to=%2Fafter&error_redirect_url=%2F%2Fevil.example.com",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/after?error=signup_disabled")


def test_callback_falls_back_to_redirect_target_when_new_user_redirect_is_rejected(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get(
        (
            "/auth/provider/sso/signin?provider_id=acme&request_sign_up=true"
            "&redirect_to=%2Fafter&new_user_redirect_url=%2Fauth%2Fprovider%2Fsso%2Fcallback"
        ),
        follow_redirects=False,
    )
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]

    response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/after"


def test_provision_user_runs_only_on_first_login_by_default(monkeypatch) -> None:
    calls: list[bool] = []

    def provision_user(individual: object, context: object) -> None:
        calls.append(bool(context.created))

    plugin, client_dependency, _ = build_plugin(
        provision_user=provision_user,
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin_one = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)
    state_one = parse_qs(urlparse(signin_one.headers["location"]).query)["state"][0]
    callback_one = client.get(
        f"/auth/provider/sso/callback?code=test-code-1&state={state_one}",
        follow_redirects=False,
    )

    signin_two = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)
    state_two = parse_qs(urlparse(signin_two.headers["location"]).query)["state"][0]
    callback_two = client.get(
        f"/auth/provider/sso/callback?code=test-code-2&state={state_two}",
        follow_redirects=False,
    )

    assert callback_one.status_code == 302
    assert callback_two.status_code == 302
    assert calls == [True]


def test_provision_user_runs_on_every_login_when_enabled(monkeypatch) -> None:
    calls: list[bool] = []

    def provision_user(individual: object, context: object) -> None:
        calls.append(bool(context.created))

    plugin, client_dependency, _ = build_plugin(
        provision_user=provision_user,
        provision_user_on_every_login=True,
    )
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin_one = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)
    state_one = parse_qs(urlparse(signin_one.headers["location"]).query)["state"][0]
    callback_one = client.get(
        f"/auth/provider/sso/callback?code=test-code-1&state={state_one}",
        follow_redirects=False,
    )

    signin_two = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)
    state_two = parse_qs(urlparse(signin_two.headers["location"]).query)["state"][0]
    callback_two = client.get(
        f"/auth/provider/sso/callback?code=test-code-2&state={state_two}",
        follow_redirects=False,
    )

    assert callback_one.status_code == 302
    assert callback_two.status_code == 302
    assert calls == [True, False]


@pytest.mark.asyncio
async def test_after_authenticate_assigns_verified_external_individual_with_suffix_domain() -> None:
    plugin, client_dependency, organization_adapter = build_plugin()
    belgie = DummyBelgie(client_dependency)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@dept.example.com",
        email_verified_at=datetime.now(UTC),
        name="Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )

    await plugin.after_authenticate(
        belgie=belgie,
        client=client_dependency,
        request=SimpleNamespace(),
        individual=individual,
        profile=AuthenticatedProfile(
            provider="github",
            provider_account_id="github-user-1",
            email=individual.email,
            email_verified=True,
        ),
    )

    assert organization_adapter.created_members == [
        (plugin.settings.adapter.providers["acme"].organization_id, individual.id, "member"),
    ]


@pytest.mark.asyncio
async def test_after_authenticate_uses_organization_role_resolver_for_domain_assignment() -> None:
    def organization_role_resolver(context: object) -> str:
        return "admin" if context.provider_id == "acme" else "member"

    plugin, client_dependency, organization_adapter = build_plugin(
        organization_role_resolver=organization_role_resolver,
    )
    belgie = DummyBelgie(client_dependency)
    individual = FakeIndividual(
        id=uuid4(),
        email="person@dept.example.com",
        email_verified_at=datetime.now(UTC),
        name="Person",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=[],
    )

    await plugin.after_authenticate(
        belgie=belgie,
        client=client_dependency,
        request=SimpleNamespace(),
        individual=individual,
        profile=AuthenticatedProfile(
            provider="github",
            provider_account_id="github-user-1",
            email=individual.email,
            email_verified=True,
        ),
    )

    assert organization_adapter.created_members == [
        (plugin.settings.adapter.providers["acme"].organization_id, individual.id, "admin"),
    ]


def test_signin_blocks_unverified_provider_when_domain_verification_is_enabled(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(domain_verification_enabled=True, verified_domain=False)
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?provider_id=acme", follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["detail"] == "provider must have a verified domain before sign-in"


def test_signin_allows_unverified_domain_lookup_when_verification_is_disabled(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(domain_verification_enabled=False, verified_domain=False)
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?email=person@example.com", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/authorize")


def test_saml_metadata_and_signin_routes_use_engine() -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    metadata = client.get("/auth/provider/sso/metadata/acme-saml")
    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)

    assert metadata.status_code == 200
    assert "EntityDescriptor" in metadata.text
    assert signin.status_code == 200
    assert "SAMLRequest" in signin.text


def test_saml_get_callback_with_relay_state_redirects_current_session_without_saml_response() -> None:
    saml_engine = RelayStateOnlySAMLEngine()
    plugin, client_dependency, _ = build_plugin(include_saml=True, saml_engine=saml_engine)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")
    session = SimpleNamespace(
        id=uuid4(),
        individual_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    client_dependency.sessions[session.id] = session
    client.cookies.set("session", str(session.id))

    response = client.get(
        "/auth/provider/sso/callback/acme-saml?RelayState=%2Fdashboard",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert saml_engine.finish_called is False


def test_management_routes_register_oidc_provider_return_redacted_detail() -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    management_client = StubManagementSSOClient()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    async def resolve_management_client(*_args: object, **_kwargs: object) -> StubManagementSSOClient:
        return management_client

    plugin._resolve_client = resolve_management_client
    client = TestClient(app, base_url="https://testserver.local")

    response = client.post(
        "/auth/provider/sso/providers/oidc",
        json={
            "provider_id": "acme",
            "issuer": "https://idp.example.com",
            "client_id": "client-id-1234",
            "client_secret": "client-secret",
            "domain": "example.com",
            "scopes": ["openid", "email", "profile", "offline_access"],
            "claim_mapping": {"subject": "user_id"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["provider_id"] == "acme"
    assert body["config"]["client_id"] == "****1234"
    assert "client_secret" not in body["config"]
    assert management_client.oidc_payload is not None
    assert management_client.oidc_payload["provider_id"] == "acme"
    assert management_client.oidc_payload["domain"] == "example.com"
    assert management_client.oidc_payload["claim_mapping"].subject == "user_id"


def test_management_routes_expose_provider_and_domain_operations() -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    management_client = StubManagementSSOClient()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    async def resolve_management_client(*_args: object, **_kwargs: object) -> StubManagementSSOClient:
        return management_client

    plugin._resolve_client = resolve_management_client
    client = TestClient(app, base_url="https://testserver.local")

    providers = client.get("/auth/provider/sso/providers")
    provider = client.get("/auth/provider/sso/providers/acme")
    challenge = client.post("/auth/provider/sso/providers/acme/domain/challenge")
    verified = client.post("/auth/provider/sso/providers/acme/domain/verify")
    deleted = client.delete("/auth/provider/sso/providers/acme")

    assert providers.status_code == 200
    assert providers.json()[0]["provider_id"] == "acme"
    assert provider.status_code == 200
    assert provider.json()["provider_id"] == "acme"
    assert challenge.status_code == 201
    assert challenge.json()["record_name"] == "_belgie-sso-acme.example.com"
    assert verified.status_code == 200
    assert verified.json()["domain"] == "example.com"
    assert verified.json()["domain_verified"] is True
    assert deleted.status_code == 200
    assert deleted.json() == {"success": True}
    assert management_client.last_challenge == "acme"
    assert management_client.last_verify == "acme"
    assert management_client.deleted_provider_id == "acme"


def test_management_routes_reject_invalid_oidc_auth_method_when_skip_discovery() -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.post(
        "/auth/provider/sso/providers/oidc",
        json={
            "provider_id": "route-acme",
            "issuer": "https://idp.example.com",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
            "jwks_uri": "https://idp.example.com/jwks",
            "token_endpoint_auth_method": "private_key_jwt",
            "skip_discovery": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "token endpoint auth method 'private_key_jwt' is not supported"


def test_management_routes_reject_empty_oidc_patch() -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    created = client.post(
        "/auth/provider/sso/providers/oidc",
        json={
            "provider_id": "route-acme",
            "issuer": "https://idp.example.com",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
            "jwks_uri": "https://idp.example.com/jwks",
            "skip_discovery": True,
        },
    )
    assert created.status_code == 201

    response = client.patch("/auth/provider/sso/providers/route-acme/oidc", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "at least one update field must be provided"


def test_deleting_sso_provider_does_not_delete_linked_oauth_accounts(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin()
    belgie = DummyBelgie(client_dependency)
    monkeypatch.setattr(
        plugin,
        "_build_oidc_transport",
        lambda provider: FakeOIDCTransport(email="person@route.example.com"),
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    created = client.post(
        "/auth/provider/sso/providers/oidc",
        json={
            "provider_id": "route-acme",
            "issuer": "https://idp.example.com",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "domain": "route.example.com",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "userinfo_endpoint": "https://idp.example.com/userinfo",
            "jwks_uri": "https://idp.example.com/jwks",
            "skip_discovery": True,
        },
    )
    assert created.status_code == 201

    signin = client.get("/auth/provider/sso/signin?provider_id=route-acme&request_sign_up=true", follow_redirects=False)
    state = parse_qs(urlparse(signin.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302

    deleted = client.delete("/auth/provider/sso/providers/route-acme")

    assert deleted.status_code == 200
    assert deleted.json() == {"success": True}
    assert ("sso:route-acme", "oidc-user-1") in client_dependency.adapter.oauth_accounts


def test_builtin_saml_metadata_route_returns_custom_sp_metadata_xml() -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_config_overrides={"sp_metadata_xml": "<EntityDescriptor entityID='urn:custom:sp'/>"},
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    metadata = client.get("/auth/provider/sso/metadata/acme-saml")

    assert metadata.status_code == 200
    assert metadata.text == "<EntityDescriptor entityID='urn:custom:sp'/>"


def test_render_saml_form_escapes_action_and_values() -> None:
    plugin, _, _ = build_plugin()

    response = plugin._render_saml_form(
        SAMLStartResult(
            form_action='https://idp.example.com/" onsubmit="alert(1)',
            form_fields={"RelayState": '"><script>alert(1)</script>'},
        ),
    )

    assert "&quot;" in response.body.decode()
    assert "<script>" not in response.body.decode()


def test_builtin_saml_signin_generates_signed_redirect_request(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)

    assert response.status_code == 302
    assert "SigAlg=" in response.headers["location"]
    assert "Signature=" in response.headers["location"]
    _assert_redirect_signature(response.headers["location"], payload_key="SAMLRequest", key_material=_SP_KEYS)
    request_xml = _decode_redirect_xml(response.headers["location"], payload_key="SAMLRequest")
    assert (
        request_xml.attrib["AssertionConsumerServiceURL"]
        == "http://localhost:8000/auth/provider/sso/callback/acme-saml"
    )


def test_builtin_saml_metadata_only_provider_uses_idp_metadata_for_signin_and_callback(monkeypatch) -> None:
    metadata_xml = (
        "<EntityDescriptor>"
        "<IDPSSODescriptor>"
        "<KeyDescriptor><KeyInfo><X509Data>"
        f"<X509Certificate>{_certificate_body(_IDP_KEYS.certificate)}</X509Certificate>"
        "</X509Data></KeyInfo></KeyDescriptor>"
        '<SingleSignOnService Location="https://idp-metadata.example.com/saml"/>'
        "</IDPSSODescriptor>"
        "</EntityDescriptor>"
    )
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_config_overrides={
            "sso_url": None,
            "x509_certificate": None,
            "idp_metadata_xml": metadata_xml,
        },
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)

    assert signin.status_code == 302
    assert signin.headers["location"].startswith("https://idp-metadata.example.com/saml?")
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
    )

    callback = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert callback.status_code == 302
    assert callback.headers["location"] == "/dashboard"
    assert callback.cookies.get("session") is not None


def test_builtin_saml_callback_creates_session(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert response.cookies.get("session") is not None
    assert len(client_dependency.created_oauth_accounts) == 1


def test_builtin_saml_callback_accepts_encrypted_assertions(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_config_overrides={"decryption_private_key": _SP_KEYS.private_key},
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        encrypt_assertion=True,
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert response.cookies.get("session") is not None


def test_builtin_saml_rejects_missing_assertion(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        include_assertion=False,
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/dashboard?error=oauth_callback_failed")


def test_saml_idp_initiated_callback_rejects_new_user_when_disable_implicit_sign_up_is_enabled() -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, disable_implicit_sign_up=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": "response"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/dashboard?error=signup_disabled")


def test_builtin_saml_callback_rejects_replay(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        assertion_id="assertion-replay",
    )

    first = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )
    second = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert first.status_code == 302
    assert second.status_code == 302
    assert second.headers["location"].startswith("/dashboard?error=saml_replay_detected")


def test_builtin_saml_callback_rejects_replay_across_callback_and_acs_routes(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        assertion_id="assertion-cross-endpoint",
    )

    first = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )
    second = client.post(
        "/auth/provider/sso/acs/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert first.status_code == 302
    assert second.status_code == 302
    assert second.headers["location"].startswith("/dashboard?error=saml_replay_detected")


def test_builtin_saml_rejects_tampered_response(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        assertion_id="tampered-assertion",
    )
    tampered_root = ET.fromstring(base64.b64decode(saml_response))
    tampered_root.xpath(".//Attribute[@Name='email']/AttributeValue")[0].text = "attacker@example.com"
    tampered_response = base64.b64encode(ET.tostring(tampered_root, encoding="utf-8")).decode("ascii")

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": tampered_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/dashboard?error=oauth_callback_failed")


def test_builtin_saml_allows_idp_initiated_callback(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=None,
        assertion_id="idp-initiated",
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": "/welcome"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/welcome"


def test_builtin_saml_idp_initiated_callback_rejects_protocol_relative_relay_state(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=None,
        assertion_id="idp-initiated-protocol-relative",
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": "//evil.example.com/steal"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


def test_builtin_saml_idp_initiated_callback_rejects_callback_loop_relay_state(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=None,
        assertion_id="idp-initiated-loop",
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": "/auth/provider/sso/callback/acme-saml"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


def test_builtin_saml_rejects_multiple_assertions(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        duplicate_assertion=True,
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/dashboard?error=oauth_callback_failed")


def test_builtin_saml_rejects_expired_assertion(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(include_saml=True, use_builtin_saml_engine=True)
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        assertion_id="expired-assertion",
        not_on_or_after="2000-01-01T00:00:00Z",
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/dashboard?error=oauth_callback_failed")


def test_builtin_saml_rejects_deprecated_signature_algorithm_when_configured(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_settings=replace(SAMLSecuritySettings(), on_deprecated="reject"),
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
        assertion_id="bad-algorithm",
        signature_algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1",
        digest_algorithm="http://www.w3.org/2000/09/xmldsig#sha1",
    )

    response = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/dashboard?error=oauth_callback_failed")


def test_builtin_saml_logout_response_clears_session(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_settings=SAMLSecuritySettings(enable_single_logout=True),
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
    )
    callback = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )
    assert callback.status_code == 302

    signout = client.get(
        "/auth/provider/sso/signout?provider_id=acme-saml&redirect_to=%2Fbye",
        follow_redirects=False,
    )
    assert signout.status_code == 302
    logout_request_state = next(key for key in client_dependency.adapter.oauth_states if key.startswith("saml-logout:"))
    logout_request_id = logout_request_state.split(":", maxsplit=1)[1]
    logout_response = _build_logout_response_payload(in_response_to=logout_request_id)

    response = client.post(
        "/auth/provider/sso/slo/acme-saml",
        data={"SAMLResponse": logout_response, "RelayState": "/bye"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/bye"
    assert client_dependency.sessions == {}


def test_builtin_saml_logout_request_clears_session(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_settings=SAMLSecuritySettings(enable_single_logout=True),
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
    )
    callback = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )
    assert callback.status_code == 302

    saml_session_state = next(key for key in client_dependency.adapter.oauth_states if key.startswith("saml-session:"))
    session_payload = client_dependency.adapter.oauth_states[saml_session_state].payload
    logout_request = _build_logout_request_payload(
        provider_account_id=session_payload["provider_account_id"],
        session_index=session_payload["session_index"],
    )

    response = client.post(
        "/auth/provider/sso/slo/acme-saml",
        data={"SAMLRequest": logout_request, "RelayState": "/bye"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://idp.example.com/slo?")
    assert client_dependency.sessions == {}


def test_builtin_saml_signout_requires_idp_slo_url(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_config_overrides={"slo_url": None, "idp_metadata_xml": None},
        saml_settings=SAMLSecuritySettings(enable_single_logout=True),
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
    )
    callback = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )
    assert callback.status_code == 302

    signout = client.get("/auth/provider/sso/signout?provider_id=acme-saml", follow_redirects=False)

    assert signout.status_code == 400
    assert signout.json()["detail"] == "SAML provider is missing IdP slo_url"


def test_builtin_saml_logout_request_honors_logout_signature_settings(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_config_overrides={"sign_authn_request": False},
        saml_settings=SAMLSecuritySettings(enable_single_logout=True, require_signed_logout_requests=True),
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
    )
    callback = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )
    assert callback.status_code == 302

    saml_session_state = next(key for key in client_dependency.adapter.oauth_states if key.startswith("saml-session:"))
    session_payload = client_dependency.adapter.oauth_states[saml_session_state].payload
    logout_request = _build_logout_request_payload(
        provider_account_id=session_payload["provider_account_id"],
        session_index=session_payload["session_index"],
        sign_message=False,
    )

    response = client.post(
        "/auth/provider/sso/slo/acme-saml",
        data={"SAMLRequest": logout_request, "RelayState": "/bye"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "SAML message is missing a valid XML signature"


def test_builtin_saml_logout_response_honors_logout_signature_settings(monkeypatch) -> None:
    plugin, client_dependency, _ = build_plugin(
        include_saml=True,
        use_builtin_saml_engine=True,
        saml_config_overrides={"sign_authn_request": False},
        saml_settings=SAMLSecuritySettings(enable_single_logout=True, require_signed_logout_responses=True),
    )
    belgie = DummyBelgie(client_dependency)

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    client = TestClient(app, base_url="https://testserver.local")

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    request_id = client_dependency.adapter.oauth_states[relay_state].payload["request_id"]
    saml_response = _build_saml_response_payload(
        recipient="https://testserver.local/auth/provider/sso/callback/acme-saml",
        in_response_to=request_id,
    )
    callback = client.post(
        "/auth/provider/sso/callback/acme-saml",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )
    assert callback.status_code == 302

    signout = client.get(
        "/auth/provider/sso/signout?provider_id=acme-saml&redirect_to=%2Fbye",
        follow_redirects=False,
    )
    assert signout.status_code == 302
    logout_request_state = next(key for key in client_dependency.adapter.oauth_states if key.startswith("saml-logout:"))
    logout_request_id = logout_request_state.split(":", maxsplit=1)[1]
    logout_response = _build_logout_response_payload(
        in_response_to=logout_request_id,
        sign_message=False,
    )

    response = client.post(
        "/auth/provider/sso/slo/acme-saml",
        data={"SAMLResponse": logout_response, "RelayState": "/bye"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "SAML message is missing a valid XML signature"
