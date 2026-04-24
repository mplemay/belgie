# ruff: noqa: ARG002, ARG005

from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID

import pytest
import pytest_asyncio
import xmlsec
from belgie_alchemy.__tests__.fixtures.core.models import Account, Individual, OAuthAccount, OAuthState, Session
from belgie_alchemy.__tests__.fixtures.organization.models import (
    Organization as OrganizationModel,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.__tests__.fixtures.team.models import Team, TeamMember  # noqa: F401
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.organization import OrganizationAdapter
from belgie_alchemy.sso import SSOAdapter, SSODomainMixin, SSOProviderMixin
from belgie_core import Belgie, BelgieClient, BelgieSettings
from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo
from belgie_organization import Organization
from belgie_proto.sso import OIDCProviderConfig
from belgie_sso import EnterpriseSSO
from belgie_sso.client import SSOClient
from belgie_sso.discovery import OIDCDiscoveryResult
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lxml import etree as ET  # noqa: N812
from signxml import XMLSigner, methods
from signxml.algorithms import CanonicalizationMethod, DigestAlgorithm, SignatureMethod
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class SSOProvider(DataclassBase, PrimaryKeyMixin, TimestampMixin, SSOProviderMixin):
    pass


class SSODomain(DataclassBase, PrimaryKeyMixin, TimestampMixin, SSODomainMixin):
    pass


class FakeOIDCTransport:
    def __init__(self) -> None:
        self.config = SimpleNamespace(use_pkce=True)

    def should_use_nonce(self, scopes):
        return True

    async def generate_authorization_url(self, state: str, **kwargs: object) -> str:
        return f"https://idp.example.com/authorize?state={state}"

    async def resolve_server_metadata(self) -> dict[str, str]:
        return {"issuer": "https://idp.example.com"}

    def validate_issuer_parameter(self, issuer: str | None, metadata: dict[str, str]) -> None:
        return None

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
            email="person@dept.example.com",
            email_verified=True,
            name="Person Example",
            raw={
                "sub": "oidc-user-1",
                "email": "person@dept.example.com",
                "email_verified": True,
                "name": "Person Example",
            },
        )


@dataclass(frozen=True, slots=True)
class _KeyMaterial:
    private_key: str
    certificate: str


def _build_key_material(common_name: str) -> _KeyMaterial:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
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
}
_DIGEST_METHODS = {
    "sha256": DigestAlgorithm.SHA256,
    "sha384": DigestAlgorithm.SHA384,
    "sha512": DigestAlgorithm.SHA512,
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


def _encode_xml(element: ET._Element) -> str:
    return base64.b64encode(ET.tostring(element, encoding="utf-8", xml_declaration=False)).decode("ascii")


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


def _build_saml_response_payload(
    *,
    recipient: str,
    in_response_to: str,
    assertion_id: str = "assertion-1",
    provider_account_id: str = "saml-user-1",
    email: str = "person@example.com",
    session_index: str = "session-index-1",
) -> str:
    response = ET.Element(
        "Response",
        ID="response-1",
        Version="2.0",
        Destination=recipient,
        InResponseTo=in_response_to,
    )
    ET.SubElement(response, "Issuer").text = "https://idp.example.com"
    status = ET.SubElement(response, "Status")
    ET.SubElement(status, "StatusCode", Value="urn:oasis:names:tc:SAML:2.0:status:Success")
    assertion = ET.Element("Assertion", ID=assertion_id)
    ET.SubElement(assertion, "Issuer").text = "https://idp.example.com"
    subject = ET.SubElement(assertion, "Subject")
    ET.SubElement(subject, "NameID").text = provider_account_id
    subject_confirmation = ET.SubElement(subject, "SubjectConfirmation")
    ET.SubElement(
        subject_confirmation,
        "SubjectConfirmationData",
        {
            "Recipient": recipient,
            "InResponseTo": in_response_to,
            "NotOnOrAfter": "2099-01-01T00:00:00Z",
        },
    )
    ET.SubElement(
        assertion,
        "Conditions",
        {
            "NotBefore": "2000-01-01T00:00:00Z",
            "NotOnOrAfter": "2099-01-01T00:00:00Z",
        },
    )
    attribute_statement = ET.SubElement(assertion, "AttributeStatement")
    for attribute_name, attribute_value in {
        "email": email,
        "email_verified": "true",
        "name": "Saml Person",
    }.items():
        attribute = ET.SubElement(attribute_statement, "Attribute", Name=attribute_name)
        ET.SubElement(attribute, "AttributeValue").text = attribute_value
    ET.SubElement(assertion, "AuthnStatement", SessionIndex=session_index)
    response.append(_sign_element(assertion, key_material=_IDP_KEYS))
    _encrypt_assertion(response)
    return _encode_xml(response)


def _build_logout_response_payload(*, in_response_to: str) -> str:
    logout_response = ET.Element("LogoutResponse", ID="logout-response-1", Version="2.0", InResponseTo=in_response_to)
    ET.SubElement(logout_response, "Issuer").text = "https://idp.example.com"
    status = ET.SubElement(logout_response, "Status")
    ET.SubElement(status, "StatusCode", Value="urn:oasis:names:tc:SAML:2.0:status:Success")
    return _encode_xml(_sign_element(logout_response, key_material=_IDP_KEYS))


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


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    database_path = tmp_path / "belgie-sso.sqlite3"
    engine = create_async_engine(
        URL.create("sqlite+aiosqlite", database=str(database_path)),
        echo=False,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(DataclassBase.metadata.create_all)

    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_enterprise_sso_flow_assigns_user_to_existing_org(monkeypatch, session_factory) -> None:
    core_adapter = BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    )
    organization_adapter = OrganizationAdapter(
        organization=OrganizationModel,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
    )
    sso_adapter = SSOAdapter(
        sso_provider=SSOProvider,
        sso_domain=SSODomain,
    )

    settings = BelgieSettings(secret="secret", base_url="http://localhost:8000")

    async def database():
        async with session_factory() as session:
            yield session

    belgie = Belgie(
        settings=settings,
        adapter=core_adapter,
        database=database,
    )
    belgie.add_plugin(Organization(adapter=organization_adapter))
    sso_settings = EnterpriseSSO(adapter=sso_adapter)
    sso_plugin = belgie.add_plugin(sso_settings)

    async with session_factory() as session:
        owner = await core_adapter.create_individual(
            session,
            email="owner@example.com",
            name="Owner",
            email_verified_at=datetime.now(UTC),
        )
        organization = await organization_adapter.create_organization(
            session,
            name="Acme",
            slug="acme",
        )
        await organization_adapter.create_member(
            session,
            organization_id=organization.id,
            individual_id=owner.id,
            role="owner",
        )

        management_client = SSOClient(
            client=BelgieClient(
                db=session,
                adapter=core_adapter,
                session_manager=belgie.session_manager,
                cookie_settings=belgie.settings.cookie,
            ),
            settings=sso_settings,
            organization_adapter=organization_adapter,
            current_individual=owner,
        )

        monkeypatch.setattr(
            "belgie_sso.client.discover_oidc_configuration",
            AsyncMock(
                return_value=OIDCDiscoveryResult(
                    issuer="https://idp.example.com",
                    config=OIDCProviderConfig(
                        issuer="https://idp.example.com",
                        client_id="client-id",
                        client_secret="client-secret",
                        authorization_endpoint="https://idp.example.com/authorize",
                        token_endpoint="https://idp.example.com/token",
                        userinfo_endpoint="https://idp.example.com/userinfo",
                    ),
                ),
            ),
        )

        provider = await management_client.register_oidc_provider(
            organization_id=organization.id,
            provider_id="acme",
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            domains=["example.com"],
        )
        domain = (await sso_adapter.list_domains_for_provider(session, sso_provider_id=provider.id))[0]
        await sso_adapter.update_domain(session, domain_id=domain.id, verified_at=datetime.now(UTC))

    monkeypatch.setattr(sso_plugin, "_build_oidc_transport", lambda provider: FakeOIDCTransport())

    app = FastAPI()
    app.include_router(belgie.router)
    client = TestClient(app, base_url="https://testserver.local")

    signin_response = client.get(
        "/auth/provider/sso/signin?email=person@dept.example.com",
        follow_redirects=False,
    )

    assert signin_response.status_code == 302
    state = parse_qs(urlparse(signin_response.headers["location"]).query)["state"][0]

    callback_response = client.get(
        f"/auth/provider/sso/callback?code=test-code&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/dashboard"

    async with session_factory() as session:
        created_user = await core_adapter.get_individual_by_email(session, "person@dept.example.com")
        assert created_user is not None
        member = await organization_adapter.get_member(
            session,
            organization_id=organization.id,
            individual_id=created_user.id,
        )
        assert member is not None
        assert member.role == "member"


@pytest.mark.asyncio
async def test_encrypted_saml_signin_and_sp_initiated_logout_flow(session_factory) -> None:
    core_adapter = BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    )
    sso_adapter = SSOAdapter(
        sso_provider=SSOProvider,
        sso_domain=SSODomain,
    )

    settings = BelgieSettings(secret="secret", base_url="http://localhost:8000")

    async def database():
        async with session_factory() as session:
            yield session

    belgie = Belgie(
        settings=settings,
        adapter=core_adapter,
        database=database,
    )
    sso_settings = EnterpriseSSO(adapter=sso_adapter, trust_email_verified=True)
    belgie.add_plugin(sso_settings)

    async with session_factory() as session:
        owner = await core_adapter.create_individual(
            session,
            email="owner@example.com",
            name="Owner",
            email_verified_at=datetime.now(UTC),
        )
        management_client = SSOClient(
            client=BelgieClient(
                db=session,
                adapter=core_adapter,
                session_manager=belgie.session_manager,
                cookie_settings=belgie.settings.cookie,
            ),
            settings=sso_settings,
            current_individual=owner,
        )
        await management_client.register_saml_provider(
            provider_id="acme-saml",
            issuer="https://idp.example.com",
            entity_id="urn:acme:sp",
            sso_url="https://idp.example.com/saml",
            slo_url="https://idp.example.com/slo",
            x509_certificate=_IDP_KEYS.certificate,
            private_key=_SP_KEYS.private_key,
            signing_certificate=_SP_KEYS.certificate,
            decryption_private_key=_SP_KEYS.private_key,
        )

    app = FastAPI()
    app.include_router(belgie.router)
    client = TestClient(app, base_url="https://testserver.local")

    metadata = client.get("/auth/provider/sso/metadata/acme-saml")

    assert metadata.status_code == 200
    assert "EntityDescriptor" in metadata.text

    signin = client.get("/auth/provider/sso/signin?provider_id=acme-saml", follow_redirects=False)

    assert signin.status_code == 302
    relay_state = parse_qs(urlparse(signin.headers["location"]).query)["RelayState"][0]
    async with session_factory() as session:
        pending_state = await core_adapter.get_oauth_state(session, relay_state)
        assert pending_state is not None
        assert isinstance(pending_state.payload, dict)
        request_id = pending_state.payload["request_id"]

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
    session_cookie = client.cookies.get(belgie.settings.cookie.name)
    assert session_cookie is not None

    async with session_factory() as session:
        created_user = await core_adapter.get_individual_by_email(session, "person@example.com")
        assert created_user is not None
        saml_session_state = await core_adapter.get_oauth_state(session, f"saml-session:{session_cookie}")
        assert saml_session_state is not None
        assert isinstance(saml_session_state.payload, dict)
        assert saml_session_state.payload["provider_id"] == "acme-saml"
        assert saml_session_state.payload["session_index"] == "session-index-1"

    signout = client.get(
        "/auth/provider/sso/signout?provider_id=acme-saml&redirect_to=%2Fbye",
        follow_redirects=False,
    )

    assert signout.status_code == 302
    logout_request = _decode_redirect_xml(signout.headers["location"], payload_key="SAMLRequest")
    logout_request_id = logout_request.attrib["ID"]

    logout_response = _build_logout_response_payload(in_response_to=logout_request_id)
    slo = client.post(
        "/auth/provider/sso/slo/acme-saml",
        data={"SAMLResponse": logout_response, "RelayState": "/bye"},
        follow_redirects=False,
    )

    assert slo.status_code == 302
    assert slo.headers["location"] == "/bye"

    async with session_factory() as session:
        assert await belgie.session_manager.get_session(session, UUID(session_cookie)) is None
        assert await core_adapter.get_oauth_state(session, f"saml-session:{session_cookie}") is None
