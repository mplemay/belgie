from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode, urlparse

import pytest
import xmlsec
from belgie_proto.sso import SAMLProviderConfig
from belgie_sso.saml import BuiltinSAMLEngine
from belgie_sso.settings import SAMLSecuritySettings
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree as ET  # noqa: N812
from signxml import XMLSigner, methods
from signxml.algorithms import CanonicalizationMethod, DigestAlgorithm, SignatureMethod
from starlette.requests import Request


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


def _build_config(**overrides: object) -> SAMLProviderConfig:
    payload = {
        "entity_id": "urn:acme:sp",
        "sso_url": "https://idp.example.com/saml",
        "x509_certificate": _IDP_KEYS.certificate,
        "slo_url": "https://idp.example.com/slo",
        "binding": "post",
        "allow_idp_initiated": False,
        "want_assertions_signed": True,
        "sign_authn_request": True,
        "signature_algorithm": "rsa-sha256",
        "digest_algorithm": "sha256",
        "private_key": _SP_KEYS.private_key,
        "signing_certificate": _SP_KEYS.certificate,
        "decryption_private_key": _SP_KEYS.private_key,
    }
    payload.update(overrides)
    return SAMLProviderConfig(**payload)


def _build_provider() -> SimpleNamespace:
    return SimpleNamespace(issuer="https://idp.example.com")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode_xml(element: ET._Element) -> str:
    return base64.b64encode(ET.tostring(element, encoding="utf-8", xml_declaration=False)).decode("ascii")


def _build_post_request(url: str, *, form_fields: dict[str, str]) -> Request:
    parsed = urlparse(url)
    body = urlencode(form_fields).encode("utf-8")
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": parsed.scheme,
        "path": parsed.path,
        "raw_path": parsed.path.encode("utf-8"),
        "root_path": "",
        "query_string": parsed.query.encode("utf-8"),
        "headers": [
            (b"host", parsed.netloc.encode("utf-8")),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode("utf-8")),
        ],
        "client": ("testclient", 50000),
        "server": (parsed.hostname or "testserver.local", parsed.port or 443),
    }
    return Request(scope, receive)


def _build_assertion(
    *,
    recipient: str,
    issuer: str,
    in_response_to: str | None,
    assertion_id: str,
    provider_account_id: str,
    email: str,
    email_verified: str,
    name: str,
    session_index: str,
    not_before: str,
    not_on_or_after: str,
    sign_assertion: bool,
) -> ET._Element:
    assertion = ET.Element("Assertion", ID=assertion_id)
    ET.SubElement(assertion, "Issuer").text = issuer
    subject = ET.SubElement(assertion, "Subject")
    ET.SubElement(subject, "NameID").text = provider_account_id
    subject_confirmation = ET.SubElement(subject, "SubjectConfirmation")
    confirmation_attributes = {
        "Recipient": recipient,
        "NotOnOrAfter": not_on_or_after,
    }
    if in_response_to is not None:
        confirmation_attributes["InResponseTo"] = in_response_to
    ET.SubElement(subject_confirmation, "SubjectConfirmationData", confirmation_attributes)
    ET.SubElement(assertion, "Conditions", {"NotBefore": not_before, "NotOnOrAfter": not_on_or_after})
    attribute_statement = ET.SubElement(assertion, "AttributeStatement")
    for attribute_name, attribute_value in {
        "email": email,
        "email_verified": email_verified,
        "name": name,
    }.items():
        attribute = ET.SubElement(attribute_statement, "Attribute", Name=attribute_name)
        ET.SubElement(attribute, "AttributeValue").text = attribute_value
    ET.SubElement(assertion, "AuthnStatement", SessionIndex=session_index)
    return _sign_element(assertion, key_material=_IDP_KEYS) if sign_assertion else assertion


def _encrypt_assertion(response: ET._Element, *, certificate: str) -> None:
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
    manager.add_key(xmlsec.Key.from_memory(certificate, xmlsec.constants.KeyDataFormatCertPem, None))
    context = xmlsec.EncryptionContext(manager)
    context.key = xmlsec.Key.generate(xmlsec.constants.KeyDataAes, 128, xmlsec.constants.KeyDataTypeSession)
    encrypted_data = context.encrypt_xml(encrypted_data, assertion)
    encrypted_assertion = ET.Element("EncryptedAssertion")
    encrypted_assertion.append(encrypted_data)
    response.append(encrypted_assertion)


def _build_saml_response_payload(  # noqa: C901
    *,
    recipient: str,
    issuer: str = "https://idp.example.com",
    in_response_to: str | None = "request-1",
    assertion_id: str = "assertion-1",
    provider_account_id: str = "saml-user-1",
    email: str = "Person@Example.com",
    email_verified: str = "true",
    name: str = "Saml Person",
    session_index: str = "session-1",
    not_before: str = "2000-01-01T00:00:00Z",
    not_on_or_after: str = "2099-01-01T00:00:00Z",
    sign_assertion: bool = True,
    sign_response: bool = False,
    nested_assertion: bool = False,
    duplicate_assertion: bool = False,
    encrypt_assertion: bool = False,
    signature_algorithm: str | None = None,
    digest_algorithm: str | None = None,
) -> str:
    response = ET.Element("Response", ID="response-1", Version="2.0", Destination=recipient)
    if in_response_to is not None:
        response.attrib["InResponseTo"] = in_response_to
    ET.SubElement(response, "Issuer").text = issuer
    status = ET.SubElement(response, "Status")
    ET.SubElement(status, "StatusCode", Value="urn:oasis:names:tc:SAML:2.0:status:Success")

    assertion = _build_assertion(
        recipient=recipient,
        issuer=issuer,
        in_response_to=in_response_to,
        assertion_id=assertion_id,
        provider_account_id=provider_account_id,
        email=email,
        email_verified=email_verified,
        name=name,
        session_index=session_index,
        not_before=not_before,
        not_on_or_after=not_on_or_after,
        sign_assertion=sign_assertion,
    )
    if nested_assertion:
        wrapper = ET.SubElement(response, "Wrapper")
        wrapper.append(assertion)
    else:
        response.append(assertion)

    if duplicate_assertion:
        response.append(
            _build_assertion(
                recipient=recipient,
                issuer=issuer,
                in_response_to=in_response_to,
                assertion_id=f"{assertion_id}-extra",
                provider_account_id=provider_account_id,
                email=email,
                email_verified=email_verified,
                name=name,
                session_index=session_index,
                not_before=not_before,
                not_on_or_after=not_on_or_after,
                sign_assertion=sign_assertion,
            ),
        )

    if encrypt_assertion:
        _encrypt_assertion(response, certificate=_SP_KEYS.certificate)

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
    session_index: str = "session-1",
    sign_message: bool = True,
) -> str:
    logout_request = ET.Element("LogoutRequest", ID="logout-request-1", Version="2.0")
    ET.SubElement(logout_request, "Issuer").text = issuer
    ET.SubElement(logout_request, "NameID").text = provider_account_id
    ET.SubElement(logout_request, "SessionIndex").text = session_index
    return _encode_xml(_sign_element(logout_request, key_material=_IDP_KEYS) if sign_message else logout_request)


def _build_logout_response_payload(
    *,
    in_response_to: str,
    issuer: str = "https://idp.example.com",
    sign_message: bool = True,
) -> str:
    logout_response = ET.Element("LogoutResponse", ID="logout-response-1", Version="2.0", InResponseTo=in_response_to)
    ET.SubElement(logout_response, "Issuer").text = issuer
    status = ET.SubElement(logout_response, "Status")
    ET.SubElement(status, "StatusCode", Value="urn:oasis:names:tc:SAML:2.0:status:Success")
    return _encode_xml(_sign_element(logout_response, key_material=_IDP_KEYS) if sign_message else logout_response)


@pytest.mark.asyncio
async def test_metadata_xml_returns_custom_sp_metadata_verbatim() -> None:
    engine = BuiltinSAMLEngine(settings=SAMLSecuritySettings())
    custom_metadata = "<EntityDescriptor entityID='urn:custom:sp'/>"

    metadata = await engine.metadata_xml(
        provider=_build_provider(),
        config=_build_config(sp_metadata_xml=custom_metadata),
        acs_url="https://testserver.local/auth/provider/sso/callback/acme-saml",
    )

    assert metadata == custom_metadata


@pytest.mark.asyncio
async def test_metadata_xml_uses_sp_slo_url_instead_of_idp_slo_url() -> None:
    engine = BuiltinSAMLEngine(settings=SAMLSecuritySettings())
    acs_url = "https://testserver.local/auth/provider/sso/callback/acme-saml"

    metadata = await engine.metadata_xml(
        provider=_build_provider(),
        config=_build_config(slo_url="https://idp.example.com/slo"),
        acs_url=acs_url,
    )

    root = ET.fromstring(metadata.encode("utf-8"))
    single_logout = next(element for element in root.iter() if element.tag.endswith("SingleLogoutService"))
    assert single_logout.attrib["Location"] == "https://testserver.local/auth/provider/sso/slo/acme-saml"


@pytest.mark.asyncio
async def test_finish_signin_rejects_nested_assertions() -> None:
    engine = BuiltinSAMLEngine(settings=SAMLSecuritySettings())
    request_url = "https://testserver.local/auth/provider/sso/callback/acme-saml"

    with pytest.raises(RuntimeError, match="SAML response must contain exactly one assertion"):
        await engine.finish_signin(
            provider=_build_provider(),
            config=_build_config(),
            request=_build_post_request(
                request_url,
                form_fields={
                    "SAMLResponse": _build_saml_response_payload(
                        recipient=request_url,
                        nested_assertion=True,
                    ),
                },
            ),
            relay_state="state",
            request_id="request-1",
        )


@pytest.mark.asyncio
async def test_finish_signin_decrypts_encrypted_assertions() -> None:
    engine = BuiltinSAMLEngine(settings=SAMLSecuritySettings())
    request_url = "https://testserver.local/auth/provider/sso/callback/acme-saml"

    profile = await engine.finish_signin(
        provider=_build_provider(),
        config=_build_config(),
        request=_build_post_request(
            request_url,
            form_fields={
                "SAMLResponse": _build_saml_response_payload(
                    recipient=request_url,
                    encrypt_assertion=True,
                ),
            },
        ),
        relay_state="state",
        request_id="request-1",
    )

    assert profile.provider_account_id == "saml-user-1"
    assert profile.email == "person@example.com"
    assert profile.assertion_id == "assertion-1"


@pytest.mark.asyncio
async def test_finish_signin_rejects_disallowed_signature_and_digest_algorithms() -> None:
    engine = BuiltinSAMLEngine(settings=SAMLSecuritySettings())
    request_url = "https://testserver.local/auth/provider/sso/callback/acme-saml"

    with pytest.raises(RuntimeError, match="SAML signature algorithm is not allowed"):
        await engine.finish_signin(
            provider=_build_provider(),
            config=_build_config(),
            request=_build_post_request(
                request_url,
                form_fields={
                    "SAMLResponse": _build_saml_response_payload(
                        recipient=request_url,
                        signature_algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1",
                        digest_algorithm="http://www.w3.org/2000/09/xmldsig#sha1",
                    ),
                },
            ),
            relay_state="state",
            request_id="request-1",
        )


@pytest.mark.asyncio
async def test_finish_signin_enforces_timestamp_boundaries(monkeypatch) -> None:
    frozen = datetime(2026, 4, 23, 12, 0, tzinfo=UTC)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None) -> datetime:
            return frozen if tz is not None else frozen.replace(tzinfo=None)

    monkeypatch.setattr("belgie_sso.saml.datetime", FrozenDatetime)
    engine = BuiltinSAMLEngine(settings=SAMLSecuritySettings(clock_skew_seconds=0))
    request_url = "https://testserver.local/auth/provider/sso/callback/acme-saml"

    with pytest.raises(RuntimeError, match="SAML assertion has expired"):
        await engine.finish_signin(
            provider=_build_provider(),
            config=_build_config(),
            request=_build_post_request(
                request_url,
                form_fields={
                    "SAMLResponse": _build_saml_response_payload(
                        recipient=request_url,
                        not_before=_iso(frozen - timedelta(minutes=1)),
                        not_on_or_after=_iso(frozen),
                    ),
                },
            ),
            relay_state="state",
            request_id="request-1",
        )

    profile = await engine.finish_signin(
        provider=_build_provider(),
        config=_build_config(),
        request=_build_post_request(
            request_url,
            form_fields={
                "SAMLResponse": _build_saml_response_payload(
                    recipient=request_url,
                    not_before=_iso(frozen),
                    not_on_or_after=_iso(frozen + timedelta(minutes=1)),
                    assertion_id="assertion-boundary",
                ),
            },
        ),
        relay_state="state",
        request_id="request-1",
    )

    assert profile.assertion_id == "assertion-boundary"


@pytest.mark.asyncio
async def test_start_logout_requires_idp_slo_url() -> None:
    engine = BuiltinSAMLEngine(settings=SAMLSecuritySettings())

    with pytest.raises(RuntimeError, match="SAML provider is missing IdP slo_url"):
        await engine.start_logout(
            provider=_build_provider(),
            config=_build_config(slo_url=None, idp_metadata_xml=None),
            slo_url="https://testserver.local/auth/provider/sso/slo/acme-saml",
            relay_state="/signed-out",
            provider_account_id="saml-user-1",
            session_index="session-1",
        )


@pytest.mark.asyncio
async def test_finish_logout_uses_logout_request_signature_setting() -> None:
    engine = BuiltinSAMLEngine(
        settings=SAMLSecuritySettings(require_signed_logout_requests=True),
    )
    request_url = "https://testserver.local/auth/provider/sso/slo/acme-saml"
    config = _build_config(sign_authn_request=False)

    with pytest.raises(RuntimeError, match="SAML message is missing a valid XML signature"):
        await engine.finish_logout(
            provider=_build_provider(),
            config=config,
            request=_build_post_request(
                request_url,
                form_fields={"SAMLRequest": _build_logout_request_payload(sign_message=False)},
            ),
        )

    permissive_engine = BuiltinSAMLEngine(
        settings=SAMLSecuritySettings(require_signed_logout_requests=False),
    )
    profile = await permissive_engine.finish_logout(
        provider=_build_provider(),
        config=config,
        request=_build_post_request(
            request_url,
            form_fields={"SAMLRequest": _build_logout_request_payload(sign_message=False)},
        ),
    )

    assert profile.flow == "request"


@pytest.mark.asyncio
async def test_finish_logout_uses_logout_response_signature_setting() -> None:
    engine = BuiltinSAMLEngine(
        settings=SAMLSecuritySettings(require_signed_logout_responses=True),
    )
    request_url = "https://testserver.local/auth/provider/sso/slo/acme-saml"
    config = _build_config(sign_authn_request=False)

    with pytest.raises(RuntimeError, match="SAML message is missing a valid XML signature"):
        await engine.finish_logout(
            provider=_build_provider(),
            config=config,
            request=_build_post_request(
                request_url,
                form_fields={
                    "SAMLResponse": _build_logout_response_payload(
                        in_response_to="logout-request-1",
                        sign_message=False,
                    ),
                },
            ),
        )

    permissive_engine = BuiltinSAMLEngine(
        settings=SAMLSecuritySettings(require_signed_logout_responses=False),
    )
    profile = await permissive_engine.finish_logout(
        provider=_build_provider(),
        config=config,
        request=_build_post_request(
            request_url,
            form_fields={
                "SAMLResponse": _build_logout_response_payload(in_response_to="logout-request-1", sign_message=False),
            },
        ),
    )

    assert profile.flow == "response"
