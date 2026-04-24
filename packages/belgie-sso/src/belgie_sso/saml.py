from __future__ import annotations

import base64
import secrets
import textwrap
import zlib
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable
from urllib.parse import quote, unquote, urlparse, urlunparse

import xmlsec
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, types
from lxml import etree as ET  # noqa: N812
from signxml import XMLSigner, XMLVerifier, methods
from signxml.algorithms import CanonicalizationMethod, DigestAlgorithm, SignatureMethod
from signxml.verifier import SignatureConfiguration

from belgie_sso.utils import parse_bool_claim

if TYPE_CHECKING:
    from collections.abc import Collection

    from belgie_proto.core.json import JSONValue
    from belgie_proto.sso import SAMLProviderConfig, SSOProviderProtocol
    from fastapi import Request

    from belgie_sso.settings import SAMLSecuritySettings

_METADATA_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
_PROTOCOL_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
_ASSERTION_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"
_POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
_REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
_SUCCESS_STATUS = "urn:oasis:names:tc:SAML:2.0:status:Success"
_SIGNATURE_ALGORITHM_URIS = {
    "rsa-sha256": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
    "rsa-sha384": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha384",
    "rsa-sha512": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha512",
}
_DIGEST_ALGORITHM_URIS = {
    "sha256": "http://www.w3.org/2001/04/xmlenc#sha256",
    "sha384": "http://www.w3.org/2001/04/xmldsig-more#sha384",
    "sha512": "http://www.w3.org/2001/04/xmlenc#sha512",
}
_SIGNATURE_ALGORITHM_BY_URI = {value: key for key, value in _SIGNATURE_ALGORITHM_URIS.items()}
_DIGEST_ALGORITHM_BY_URI = {value: key for key, value in _DIGEST_ALGORITHM_URIS.items()}
_SIGNXML_SIGNATURE_METHODS = {
    "rsa-sha256": SignatureMethod.RSA_SHA256,
    "rsa-sha384": SignatureMethod.RSA_SHA384,
    "rsa-sha512": SignatureMethod.RSA_SHA512,
}
_SIGNXML_DIGEST_ALGORITHMS = {
    "sha256": DigestAlgorithm.SHA256,
    "sha384": DigestAlgorithm.SHA384,
    "sha512": DigestAlgorithm.SHA512,
}

ET.register_namespace("md", _METADATA_NS)
ET.register_namespace("samlp", _PROTOCOL_NS)
ET.register_namespace("saml", _ASSERTION_NS)
ET.register_namespace("ds", _DS_NS)


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


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
    assertion_id: str | None = None
    in_response_to: str | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class SAMLLogoutResult:
    redirect_url: str | None = None
    form_action: str | None = None
    form_fields: dict[str, str] = field(default_factory=dict)
    request_id: str | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class SAMLLogoutProfile:
    flow: Literal["request", "response"]
    request_id: str | None
    in_response_to: str | None
    provider_account_id: str | None
    session_index: str | None
    relay_state: str | None


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


@runtime_checkable
class SAMLLogoutEngine(Protocol):
    async def start_logout(  # noqa: PLR0913
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        slo_url: str,
        relay_state: str,
        provider_account_id: str,
        session_index: str | None,
    ) -> SAMLLogoutResult: ...

    async def finish_logout(
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        request: Request,
    ) -> SAMLLogoutProfile: ...

    async def build_logout_response(
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        slo_url: str,
        relay_state: str | None,
        in_response_to: str | None,
    ) -> SAMLLogoutResult: ...


class BuiltinSAMLEngine:
    def __init__(self, *, settings: SAMLSecuritySettings) -> None:
        self._settings = settings

    async def metadata_xml(
        self,
        *,
        provider: SSOProviderProtocol,  # noqa: ARG002
        config: SAMLProviderConfig,
        acs_url: str,
    ) -> str:
        if config.sp_metadata_xml is not None:
            metadata_bytes = config.sp_metadata_xml.encode("utf-8")
            if len(metadata_bytes) > self._settings.metadata_max_bytes:
                msg = "SAML metadata exceeds maximum size"
                raise RuntimeError(msg)
            return config.sp_metadata_xml

        descriptor = ET.Element(
            _tag(_METADATA_NS, "EntityDescriptor"),
            nsmap={"md": _METADATA_NS, "ds": _DS_NS},
            entityID=config.entity_id,
        )
        sp_descriptor = ET.SubElement(
            descriptor,
            _tag(_METADATA_NS, "SPSSODescriptor"),
            AuthnRequestsSigned=str(config.sign_authn_request).lower(),
            WantAssertionsSigned=str(config.want_assertions_signed).lower(),
            protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol",
        )
        if config.name_id_format:
            name_id_format = ET.SubElement(sp_descriptor, _tag(_METADATA_NS, "NameIDFormat"))
            name_id_format.text = config.name_id_format
        ET.SubElement(
            sp_descriptor,
            _tag(_METADATA_NS, "AssertionConsumerService"),
            Binding=_POST_BINDING if config.binding == "post" else _REDIRECT_BINDING,
            Location=acs_url,
            index="0",
            isDefault="true",
        )
        ET.SubElement(
            sp_descriptor,
            _tag(_METADATA_NS, "SingleLogoutService"),
            Binding=_POST_BINDING if config.binding == "post" else _REDIRECT_BINDING,
            Location=_derive_slo_url(acs_url),
        )
        if config.signing_certificate:
            key_descriptor = ET.SubElement(sp_descriptor, _tag(_METADATA_NS, "KeyDescriptor"), use="signing")
            key_info = ET.SubElement(key_descriptor, _tag(_DS_NS, "KeyInfo"))
            x509_data = ET.SubElement(key_info, _tag(_DS_NS, "X509Data"))
            certificate = ET.SubElement(x509_data, _tag(_DS_NS, "X509Certificate"))
            certificate.text = _certificate_body(config.signing_certificate)
        metadata_bytes = ET.tostring(descriptor, encoding="utf-8", xml_declaration=False)
        if len(metadata_bytes) > self._settings.metadata_max_bytes:
            msg = "SAML metadata exceeds maximum size"
            raise RuntimeError(msg)
        return metadata_bytes.decode("utf-8")

    async def start_signin(
        self,
        *,
        provider: SSOProviderProtocol,  # noqa: ARG002
        config: SAMLProviderConfig,
        acs_url: str,
        relay_state: str,
    ) -> SAMLStartResult:
        request_id = _build_request_id()
        root = ET.Element(
            _tag(_PROTOCOL_NS, "AuthnRequest"),
            nsmap={"samlp": _PROTOCOL_NS, "saml": _ASSERTION_NS, "ds": _DS_NS},
            ID=request_id,
            Version="2.0",
            IssueInstant=_xml_timestamp(datetime.now(UTC)),
            Destination=_resolved_sso_url(config),
            AssertionConsumerServiceURL=acs_url,
            ProtocolBinding=_POST_BINDING if config.binding == "post" else _REDIRECT_BINDING,
        )
        issuer = ET.SubElement(root, _tag(_ASSERTION_NS, "Issuer"))
        issuer.text = config.entity_id
        name_id_policy_attributes = {"AllowCreate": "true"}
        if config.name_id_format:
            name_id_policy_attributes["Format"] = config.name_id_format
        ET.SubElement(root, _tag(_PROTOCOL_NS, "NameIDPolicy"), **name_id_policy_attributes)
        if config.binding == "post" and config.sign_authn_request:
            root = _sign_xml(root, config=config)
        return _build_saml_result(
            destination=_resolved_sso_url(config),
            binding=config.binding,
            payload_key="SAMLRequest",
            xml=root,
            relay_state=relay_state,
            request_id=request_id,
            sign_request=config.sign_authn_request,
            signature_algorithm=config.signature_algorithm,
            private_key=config.private_key,
            private_key_passphrase=config.private_key_passphrase,
            signing_certificate=config.signing_certificate,
        )

    async def finish_signin(
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        request: Request,
        relay_state: str,  # noqa: ARG002
        request_id: str | None,
    ) -> SAMLResponseProfile:
        params = await _request_params(request)
        if not (saml_response := params.get("SAMLResponse")):
            msg = "missing SAMLResponse"
            raise RuntimeError(msg)
        binding = _request_binding(request)
        current_url = str(request.url.replace(query=""))
        root = _parse_saml_message(
            saml_response,
            max_bytes=self._settings.response_max_bytes,
            payload_name="SAMLResponse",
            compressed=binding == "redirect",
        )
        if _local_name(root.tag) != "Response":
            msg = "expected a SAML Response document"
            raise RuntimeError(msg)
        _decrypt_encrypted_assertions(root, config=config)
        callback_urls = _equivalent_callback_urls(current_url)
        _validate_destination(root, expected_destinations=callback_urls)
        _validate_response_issuer(root, expected_issuer=provider.issuer)
        _validate_algorithms(root, settings=self._settings)
        _verify_saml_message(
            root=root,
            request=request,
            payload_key="SAMLResponse",
            certificate=_verification_certificate(config),
            settings=self._settings,
            require_signed=config.want_assertions_signed,
            binding=binding,
        )
        _validate_response_status(root)
        assertion = _require_single_assertion(root)
        _validate_time_window(root, settings=self._settings)
        _validate_subject_confirmation(assertion, settings=self._settings, expected_recipients=callback_urls)
        _validate_audience(assertion, expected_audience=config.audience or config.entity_id)
        in_response_to = _response_in_response_to(root, assertion)
        if self._settings.validate_in_response_to:
            if request_id is not None and in_response_to != request_id:
                msg = "SAML response InResponseTo mismatch"
                raise RuntimeError(msg)
            if request_id is None and not config.allow_idp_initiated:
                msg = "IdP-initiated SAML responses are not allowed"
                raise RuntimeError(msg)

        attributes = _assertion_attributes(assertion)
        provider_account_id = _subject_value(assertion, attributes, claim_name=config.claim_mapping.subject)
        if provider_account_id is None:
            msg = "missing SAML subject"
            raise RuntimeError(msg)
        email = _attribute_as_string(attributes, config.claim_mapping.email)
        name = _attribute_as_string(attributes, config.claim_mapping.name) or _joined_name(
            attributes,
            first_name=config.claim_mapping.first_name,
            last_name=config.claim_mapping.last_name,
        )
        email_verified = parse_bool_claim(
            value=_attribute_as_bool_or_string(attributes, config.claim_mapping.email_verified),
        )
        session_index = _authn_statement_session_index(assertion)
        raw: dict[str, JSONValue] = {
            **attributes,
            "name_id": _name_id(assertion),
            "session_index": session_index,
            "in_response_to": in_response_to,
        }
        for target_key, claim_name in config.claim_mapping.extra_fields.items():
            if claim_name in attributes:
                raw[target_key] = attributes[claim_name]
        return SAMLResponseProfile(
            provider_account_id=provider_account_id,
            email=email.lower() if email else None,
            email_verified=email_verified,
            name=name,
            raw=raw,
            session_index=session_index,
            assertion_id=assertion.attrib.get("ID"),
            in_response_to=in_response_to,
        )

    async def start_logout(  # noqa: PLR0913
        self,
        *,
        provider: SSOProviderProtocol,  # noqa: ARG002
        config: SAMLProviderConfig,
        slo_url: str,
        relay_state: str,
        provider_account_id: str,
        session_index: str | None,
    ) -> SAMLLogoutResult:
        _ = slo_url
        destination = _resolved_idp_slo_url(config)
        request_id = _build_request_id()
        root = ET.Element(
            _tag(_PROTOCOL_NS, "LogoutRequest"),
            nsmap={"samlp": _PROTOCOL_NS, "saml": _ASSERTION_NS, "ds": _DS_NS},
            ID=request_id,
            Version="2.0",
            IssueInstant=_xml_timestamp(datetime.now(UTC)),
            Destination=destination,
        )
        issuer = ET.SubElement(root, _tag(_ASSERTION_NS, "Issuer"))
        issuer.text = config.entity_id
        name_id = ET.SubElement(root, _tag(_ASSERTION_NS, "NameID"))
        name_id.text = provider_account_id
        if session_index:
            session_index_element = ET.SubElement(root, _tag(_PROTOCOL_NS, "SessionIndex"))
            session_index_element.text = session_index
        if config.binding == "post" and config.sign_authn_request:
            root = _sign_xml(root, config=config)
        start = _build_saml_result(
            destination=destination,
            binding=config.binding,
            payload_key="SAMLRequest",
            xml=root,
            relay_state=relay_state,
            request_id=request_id,
            sign_request=config.sign_authn_request,
            signature_algorithm=config.signature_algorithm,
            private_key=config.private_key,
            private_key_passphrase=config.private_key_passphrase,
            signing_certificate=config.signing_certificate,
        )
        return SAMLLogoutResult(
            redirect_url=start.redirect_url,
            form_action=start.form_action,
            form_fields=start.form_fields,
            request_id=start.request_id,
        )

    async def finish_logout(
        self,
        *,
        provider: SSOProviderProtocol,
        config: SAMLProviderConfig,
        request: Request,
    ) -> SAMLLogoutProfile:
        params = await _request_params(request)
        relay_state = params.get("RelayState")
        binding = _request_binding(request)
        current_url = str(request.url.replace(query=""))
        if saml_request := params.get("SAMLRequest"):
            root = _parse_saml_message(
                saml_request,
                max_bytes=self._settings.response_max_bytes,
                payload_name="SAMLRequest",
                compressed=binding == "redirect",
            )
            if _local_name(root.tag) != "LogoutRequest":
                msg = "expected a SAML LogoutRequest document"
                raise RuntimeError(msg)
            _validate_destination(root, expected_destinations=(current_url,))
            _validate_response_issuer(root, expected_issuer=provider.issuer)
            _validate_algorithms(root, settings=self._settings)
            _verify_saml_message(
                root=root,
                request=request,
                payload_key="SAMLRequest",
                certificate=_verification_certificate(config),
                settings=self._settings,
                require_signed=self._settings.require_signed_logout_requests,
                binding=binding,
            )
            _validate_time_window(root, settings=self._settings)
            return SAMLLogoutProfile(
                flow="request",
                request_id=root.attrib.get("ID"),
                in_response_to=root.attrib.get("InResponseTo"),
                provider_account_id=_name_id(root),
                session_index=_first_text(root, "SessionIndex"),
                relay_state=relay_state,
            )
        if saml_response := params.get("SAMLResponse"):
            root = _parse_saml_message(
                saml_response,
                max_bytes=self._settings.response_max_bytes,
                payload_name="SAMLResponse",
                compressed=binding == "redirect",
            )
            if _local_name(root.tag) != "LogoutResponse":
                msg = "expected a SAML LogoutResponse document"
                raise RuntimeError(msg)
            _validate_destination(root, expected_destinations=(current_url,))
            _validate_response_issuer(root, expected_issuer=provider.issuer)
            _validate_algorithms(root, settings=self._settings)
            _verify_saml_message(
                root=root,
                request=request,
                payload_key="SAMLResponse",
                certificate=_verification_certificate(config),
                settings=self._settings,
                require_signed=self._settings.require_signed_logout_responses,
                binding=binding,
            )
            _validate_response_status(root)
            return SAMLLogoutProfile(
                flow="response",
                request_id=root.attrib.get("ID"),
                in_response_to=root.attrib.get("InResponseTo"),
                provider_account_id=None,
                session_index=None,
                relay_state=relay_state,
            )
        msg = "missing SAML logout payload"
        raise RuntimeError(msg)

    async def build_logout_response(
        self,
        *,
        provider: SSOProviderProtocol,  # noqa: ARG002
        config: SAMLProviderConfig,
        slo_url: str,
        relay_state: str | None,
        in_response_to: str | None,
    ) -> SAMLLogoutResult:
        _ = slo_url
        destination = _resolved_idp_slo_url(config)
        root = ET.Element(
            _tag(_PROTOCOL_NS, "LogoutResponse"),
            nsmap={"samlp": _PROTOCOL_NS, "saml": _ASSERTION_NS, "ds": _DS_NS},
            ID=_build_request_id(),
            Version="2.0",
            IssueInstant=_xml_timestamp(datetime.now(UTC)),
            Destination=destination,
        )
        if in_response_to is not None:
            root.attrib["InResponseTo"] = in_response_to
        issuer = ET.SubElement(root, _tag(_ASSERTION_NS, "Issuer"))
        issuer.text = config.entity_id
        status = ET.SubElement(root, _tag(_PROTOCOL_NS, "Status"))
        ET.SubElement(status, _tag(_PROTOCOL_NS, "StatusCode"), Value=_SUCCESS_STATUS)
        if config.binding == "post" and config.sign_authn_request:
            root = _sign_xml(root, config=config)
        start = _build_saml_result(
            destination=destination,
            binding=config.binding,
            payload_key="SAMLResponse",
            xml=root,
            relay_state=relay_state,
            request_id=root.attrib["ID"],
            sign_request=config.sign_authn_request,
            signature_algorithm=config.signature_algorithm,
            private_key=config.private_key,
            private_key_passphrase=config.private_key_passphrase,
            signing_certificate=config.signing_certificate,
        )
        return SAMLLogoutResult(
            redirect_url=start.redirect_url,
            form_action=start.form_action,
            form_fields=start.form_fields,
            request_id=start.request_id,
        )


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


def _build_request_id() -> str:
    return f"_{secrets.token_urlsafe(24)}"


def _xml_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _derive_slo_url(acs_url: str) -> str:
    parsed = urlparse(acs_url)
    if "/callback/" in parsed.path:
        path = parsed.path.replace("/callback/", "/slo/", 1)
    elif parsed.path.endswith("/callback"):
        path = parsed.path[: -len("/callback")] + "/slo"
    else:
        path = parsed.path.rstrip("/") + "/slo"
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def _equivalent_callback_urls(current_url: str) -> tuple[str, ...]:
    parsed = urlparse(current_url)
    if "/callback/" in parsed.path:
        alternate_path = parsed.path.replace("/callback/", "/acs/", 1)
    elif "/acs/" in parsed.path:
        alternate_path = parsed.path.replace("/acs/", "/callback/", 1)
    elif parsed.path.endswith("/callback"):
        alternate_path = parsed.path[: -len("/callback")] + "/acs"
    elif parsed.path.endswith("/acs"):
        alternate_path = parsed.path[: -len("/acs")] + "/callback"
    else:
        return (current_url,)

    alternate_url = urlunparse(parsed._replace(path=alternate_path, query="", fragment=""))
    return (current_url,) if alternate_url == current_url else (current_url, alternate_url)


def _build_saml_result(  # noqa: PLR0913
    *,
    destination: str,
    binding: str,
    payload_key: str,
    xml: ET._Element,
    relay_state: str | None,
    request_id: str,
    sign_request: bool,
    signature_algorithm: str,
    private_key: str | None,
    private_key_passphrase: str | None,
    signing_certificate: str | None,
) -> SAMLStartResult:
    if binding == "post":
        payload = base64.b64encode(_serialize_xml(xml)).decode("ascii")
        fields = {payload_key: payload}
        if relay_state is not None:
            fields["RelayState"] = relay_state
        return SAMLStartResult(form_action=destination, form_fields=fields, request_id=request_id)

    redirect_url = _redirect_url(
        destination=destination,
        payload_key=payload_key,
        xml=xml,
        relay_state=relay_state,
        sign_request=sign_request,
        signature_algorithm=signature_algorithm,
        private_key=private_key,
        private_key_passphrase=private_key_passphrase,
        signing_certificate=signing_certificate,
    )
    return SAMLStartResult(redirect_url=redirect_url, request_id=request_id)


def _redirect_url(  # noqa: PLR0913
    *,
    destination: str,
    payload_key: str,
    xml: ET._Element,
    relay_state: str | None,
    sign_request: bool,
    signature_algorithm: str,
    private_key: str | None,
    private_key_passphrase: str | None,
    signing_certificate: str | None,
) -> str:
    raw_xml = _serialize_xml(xml)
    compressed = _deflate(raw_xml)
    payload = base64.b64encode(compressed).decode("ascii")
    encoded_payload = quote(payload, safe="")
    query_parts = [f"{payload_key}={encoded_payload}"]
    if relay_state is not None:
        query_parts.append(f"RelayState={quote(relay_state, safe='')}")
    if sign_request:
        _require_signing_material(private_key, signing_certificate)
        signature_uri = _SIGNATURE_ALGORITHM_URIS.get(signature_algorithm)
        if signature_uri is None:
            msg = f"unsupported SAML signature algorithm: {signature_algorithm}"
            raise RuntimeError(msg)
        encoded_sig_alg = quote(signature_uri, safe="")
        query_parts.append(f"SigAlg={encoded_sig_alg}")
        signed_query = "&".join(query_parts)
        signature = _sign_redirect_query(
            signed_query=signed_query,
            private_key=private_key,
            private_key_passphrase=private_key_passphrase,
            signature_algorithm=signature_algorithm,
        )
        query_parts.append(f"Signature={quote(signature, safe='')}")

    parsed = urlparse(destination)
    query = "&".join(query_parts)
    if parsed.query:
        query = f"{parsed.query}&{query}"
    return urlunparse(parsed._replace(query=query))


async def _request_params(request: Request) -> dict[str, str]:
    params = dict(request.query_params)
    if request.method.upper() == "POST":
        form = await request.form()
        params.update({key: str(value) for key, value in form.items()})
    return params


def _request_binding(request: Request) -> Literal["post", "redirect"]:
    return "redirect" if request.method.upper() == "GET" else "post"


def _parse_saml_message(
    payload: str,
    *,
    max_bytes: int,
    payload_name: str,
    compressed: bool,
) -> ET._Element:
    try:
        xml_bytes = base64.b64decode(payload, validate=True)
    except Exception as exc:
        msg = f"invalid {payload_name} encoding"
        raise RuntimeError(msg) from exc
    if compressed:
        with suppress(zlib.error):
            xml_bytes = zlib.decompress(xml_bytes, wbits=-15)
    if len(xml_bytes) > max_bytes:
        msg = f"{payload_name} exceeds maximum size"
        raise RuntimeError(msg)
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        msg = "SAML XML entities are not allowed"
        raise RuntimeError(msg)
    try:
        return ET.fromstring(xml_bytes, parser=_xml_parser())
    except ET.XMLSyntaxError as exc:
        msg = f"invalid {payload_name} XML"
        raise RuntimeError(msg) from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _validate_destination(root: ET._Element, *, expected_destinations: Collection[str]) -> None:
    destination = root.attrib.get("Destination")
    if destination is not None and destination not in expected_destinations:
        msg = "SAML destination mismatch"
        raise RuntimeError(msg)


def _validate_response_issuer(root: ET._Element, *, expected_issuer: str) -> None:
    issuers = [
        element.text.strip()
        for element in root.iter()
        if _local_name(element.tag) == "Issuer" and element.text and element.text.strip()
    ]
    if issuers and any(issuer != expected_issuer for issuer in issuers):
        msg = "SAML issuer mismatch"
        raise RuntimeError(msg)


def _validate_algorithms(root: ET._Element, *, settings: SAMLSecuritySettings) -> None:
    for element in root.iter():
        if _local_name(element.tag) == "SignatureMethod":
            if (algorithm := element.attrib.get("Algorithm")) is None:
                continue
            normalized = _SIGNATURE_ALGORITHM_BY_URI.get(algorithm)
            if normalized is None or normalized not in settings.allowed_signature_algorithms:
                msg = "SAML signature algorithm is not allowed"
                raise RuntimeError(msg)
        if _local_name(element.tag) == "DigestMethod":
            if (algorithm := element.attrib.get("Algorithm")) is None:
                continue
            normalized = _DIGEST_ALGORITHM_BY_URI.get(algorithm)
            if normalized is None or normalized not in settings.allowed_digest_algorithms:
                msg = "SAML digest algorithm is not allowed"
                raise RuntimeError(msg)


def _verify_saml_message(  # noqa: PLR0913
    *,
    root: ET._Element,
    request: Request,
    payload_key: str,
    certificate: str,
    settings: SAMLSecuritySettings,
    require_signed: bool,
    binding: Literal["post", "redirect"],
) -> None:
    if binding == "redirect":
        _verify_redirect_signature(
            request=request,
            payload_key=payload_key,
            certificate=certificate,
            settings=settings,
            require_signed=require_signed,
        )
        return
    _verify_xml_signatures(
        root=root,
        certificate=certificate,
        settings=settings,
        require_signed=require_signed,
    )


def _verify_xml_signatures(
    *,
    root: ET._Element,
    certificate: str,
    settings: SAMLSecuritySettings,
    require_signed: bool,
) -> None:
    signed_elements = [element for element in root.iter() if _has_direct_signature(element)]
    if not signed_elements:
        if require_signed:
            msg = "SAML message is missing a valid XML signature"
            raise RuntimeError(msg)
        return

    expected_config = SignatureConfiguration(
        require_x509=False,
        location="./",
        expect_references=1,
        signature_methods=frozenset(
            _SIGNXML_SIGNATURE_METHODS[algorithm]
            for algorithm in settings.allowed_signature_algorithms
            if algorithm in _SIGNXML_SIGNATURE_METHODS
        ),
        digest_algorithms=frozenset(
            _SIGNXML_DIGEST_ALGORITHMS[algorithm]
            for algorithm in settings.allowed_digest_algorithms
            if algorithm in _SIGNXML_DIGEST_ALGORITHMS
        ),
        default_reference_c14n_method=CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0,
    )
    pem_certificate = _certificate_to_pem(certificate)
    for element in signed_elements:
        try:
            XMLVerifier().verify(
                element,
                x509_cert=pem_certificate,
                validate_schema=False,
                parser=_xml_parser(),
                id_attribute="ID",
                expect_config=expected_config,
            )
        except Exception as exc:
            msg = "SAML signature verification failed"
            raise RuntimeError(msg) from exc


def _verify_redirect_signature(
    *,
    request: Request,
    payload_key: str,
    certificate: str,
    settings: SAMLSecuritySettings,
    require_signed: bool,
) -> None:
    raw_payload = _raw_query_value(request, payload_key)
    raw_sig_alg = _raw_query_value(request, "SigAlg")
    raw_signature = _raw_query_value(request, "Signature")
    if raw_signature is None or raw_sig_alg is None:
        if require_signed:
            msg = "SAML message is missing a redirect signature"
            raise RuntimeError(msg)
        return
    if raw_payload is None:
        msg = "SAML redirect payload is missing"
        raise RuntimeError(msg)

    signature_algorithm = _SIGNATURE_ALGORITHM_BY_URI.get(unquote(raw_sig_alg))
    if signature_algorithm is None or signature_algorithm not in settings.allowed_signature_algorithms:
        msg = "SAML signature algorithm is not allowed"
        raise RuntimeError(msg)

    signed_parts = [f"{payload_key}={raw_payload}"]
    if (raw_relay_state := _raw_query_value(request, "RelayState")) is not None:
        signed_parts.append(f"RelayState={raw_relay_state}")
    signed_parts.append(f"SigAlg={raw_sig_alg}")

    try:
        signature = base64.b64decode(unquote(raw_signature), validate=True)
    except Exception as exc:
        msg = "invalid SAML redirect signature"
        raise RuntimeError(msg) from exc
    try:
        certificate_object = x509.load_pem_x509_certificate(_certificate_to_pem(certificate).encode("utf-8"))
        certificate_object.public_key().verify(
            signature,
            "&".join(signed_parts).encode("utf-8"),
            padding.PKCS1v15(),
            _hash_algorithm(signature_algorithm),
        )
    except Exception as exc:
        msg = "SAML redirect signature verification failed"
        raise RuntimeError(msg) from exc


def _validate_response_status(root: ET._Element) -> None:
    for element in root.iter():
        if _local_name(element.tag) != "StatusCode":
            continue
        if element.attrib.get("Value") != _SUCCESS_STATUS:
            msg = "SAML response status is not success"
            raise RuntimeError(msg)
        return
    msg = "SAML response status is missing"
    raise RuntimeError(msg)


def _decrypt_encrypted_assertions(root: ET._Element, *, config: SAMLProviderConfig) -> None:
    encrypted_assertions = [element for element in root.iter() if _local_name(element.tag) == "EncryptedAssertion"]
    if not encrypted_assertions:
        return

    manager = _decryption_key_manager(config)
    for encrypted_assertion in encrypted_assertions:
        encrypted_data = next(
            (element for element in encrypted_assertion.iter() if _local_name(element.tag) == "EncryptedData"),
            None,
        )
        if encrypted_data is None:
            msg = "encrypted SAML assertion is missing EncryptedData"
            raise RuntimeError(msg)
        try:
            decrypted = xmlsec.EncryptionContext(manager).decrypt(encrypted_data)
        except Exception as exc:
            msg = "failed to decrypt SAML assertion"
            raise RuntimeError(msg) from exc
        decrypted_tag = getattr(decrypted, "tag", None)
        if not isinstance(decrypted_tag, str) or _local_name(decrypted_tag) != "Assertion":
            msg = "encrypted SAML assertion did not decrypt to an Assertion"
            raise RuntimeError(msg)
        if (parent := encrypted_assertion.getparent()) is None:
            msg = "encrypted SAML assertion is missing a parent"
            raise RuntimeError(msg)
        if decrypted.getparent() is encrypted_assertion:
            encrypted_assertion.remove(decrypted)
        elif (decrypted_parent := decrypted.getparent()) is not None:
            decrypted_parent.remove(decrypted)
        index = parent.index(encrypted_assertion)
        parent.remove(encrypted_assertion)
        parent.insert(index, decrypted)


def _require_single_assertion(root: ET._Element) -> ET._Element:
    assertions = [element for element in root.iter() if _local_name(element.tag) == "Assertion"]
    direct_assertions = [element for element in root if _local_name(element.tag) == "Assertion"]
    if len(assertions) != 1 or len(direct_assertions) != 1 or assertions[0] is not direct_assertions[0]:
        msg = "SAML response must contain exactly one assertion"
        raise RuntimeError(msg)
    return direct_assertions[0]


def _validate_time_window(root: ET._Element, *, settings: SAMLSecuritySettings) -> None:
    now = datetime.now(UTC)
    saw_timestamp = False
    for element in root.iter():
        if _local_name(element.tag) not in {"Conditions", "SubjectConfirmationData", "LogoutRequest"}:
            continue
        not_before = _parse_saml_datetime(element.attrib.get("NotBefore"))
        not_on_or_after = _parse_saml_datetime(element.attrib.get("NotOnOrAfter"))
        saw_timestamp = saw_timestamp or not_before is not None or not_on_or_after is not None
        if not_before is not None and now.timestamp() + settings.clock_skew_seconds < not_before.timestamp():
            msg = "SAML assertion is not yet valid"
            raise RuntimeError(msg)
        if not_on_or_after is not None and now.timestamp() - settings.clock_skew_seconds >= not_on_or_after.timestamp():
            msg = "SAML assertion has expired"
            raise RuntimeError(msg)
    if settings.require_timestamps and not saw_timestamp:
        msg = "SAML assertion is missing required timestamps"
        raise RuntimeError(msg)


def _validate_subject_confirmation(
    assertion: ET._Element,
    *,
    settings: SAMLSecuritySettings,
    expected_recipients: Collection[str],
) -> None:
    confirmations = [element for element in assertion.iter() if _local_name(element.tag) == "SubjectConfirmationData"]
    if not confirmations:
        msg = "SAML subject confirmation is missing"
        raise RuntimeError(msg)
    saw_timestamp = False
    now = datetime.now(UTC)
    for element in confirmations:
        recipient = element.attrib.get("Recipient")
        if recipient is not None and recipient not in expected_recipients:
            msg = "SAML subject recipient mismatch"
            raise RuntimeError(msg)
        not_before = _parse_saml_datetime(element.attrib.get("NotBefore"))
        not_on_or_after = _parse_saml_datetime(element.attrib.get("NotOnOrAfter"))
        saw_timestamp = saw_timestamp or not_before is not None or not_on_or_after is not None
        if not_before is not None and now.timestamp() + settings.clock_skew_seconds < not_before.timestamp():
            msg = "SAML subject confirmation is not yet valid"
            raise RuntimeError(msg)
        if not_on_or_after is not None and now.timestamp() - settings.clock_skew_seconds >= not_on_or_after.timestamp():
            msg = "SAML subject confirmation has expired"
            raise RuntimeError(msg)
    if settings.require_timestamps and not saw_timestamp:
        msg = "SAML subject confirmation is missing required timestamps"
        raise RuntimeError(msg)


def _validate_audience(assertion: ET._Element, *, expected_audience: str) -> None:
    audiences = [
        element.text.strip()
        for element in assertion.iter()
        if _local_name(element.tag) == "Audience" and element.text and element.text.strip()
    ]
    if audiences and expected_audience not in audiences:
        msg = "SAML audience mismatch"
        raise RuntimeError(msg)


def _parse_saml_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _response_in_response_to(root: ET._Element, assertion: ET._Element) -> str | None:
    if root.attrib.get("InResponseTo") is not None:
        return root.attrib["InResponseTo"]
    for element in assertion.iter():
        if _local_name(element.tag) == "SubjectConfirmationData" and element.attrib.get("InResponseTo") is not None:
            return element.attrib["InResponseTo"]
    return None


def _assertion_attributes(assertion: ET._Element) -> dict[str, JSONValue]:
    attributes: dict[str, JSONValue] = {}
    for attribute in assertion.iter():
        if _local_name(attribute.tag) != "Attribute":
            continue
        if not (name := attribute.attrib.get("Name")):
            continue
        values: list[JSONValue] = [
            value.text.strip()
            for value in attribute.iter()
            if _local_name(value.tag) == "AttributeValue" and value.text and value.text.strip()
        ]
        if not values:
            continue
        attributes[name] = values[0] if len(values) == 1 else values
    return attributes


def _subject_value(
    assertion: ET._Element,
    attributes: dict[str, JSONValue],
    *,
    claim_name: str,
) -> str | None:
    if claim_name == "name_id":
        return _name_id(assertion)
    return _attribute_as_string(attributes, claim_name)


def _name_id(root: ET._Element) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == "NameID" and element.text and element.text.strip():
            return element.text.strip()
    return None


def _attribute_as_string(attributes: dict[str, JSONValue], key: str) -> str | None:
    value = attributes.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def _attribute_as_bool_or_string(attributes: dict[str, JSONValue], key: str) -> str | bool | None:
    value = attributes.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def _joined_name(
    attributes: dict[str, JSONValue],
    *,
    first_name: str,
    last_name: str,
) -> str | None:
    parts = [
        part
        for part in (
            _attribute_as_string(attributes, first_name),
            _attribute_as_string(attributes, last_name),
        )
        if part
    ]
    return " ".join(parts) if parts else None


def _authn_statement_session_index(assertion: ET._Element) -> str | None:
    for element in assertion.iter():
        if _local_name(element.tag) == "AuthnStatement":
            return element.attrib.get("SessionIndex")
    return None


def _first_text(root: ET._Element, local_name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name and element.text and element.text.strip():
            return element.text.strip()
    return None


def _serialize_xml(xml: ET._Element) -> bytes:
    return ET.tostring(xml, encoding="utf-8", xml_declaration=False)


def _deflate(value: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-15)
    return compressor.compress(value) + compressor.flush()


def _sign_redirect_query(
    *,
    signed_query: str,
    private_key: str | None,
    private_key_passphrase: str | None,
    signature_algorithm: str,
) -> str:
    _require_signing_material(private_key, "certificate")
    key = _load_private_key(private_key, passphrase=private_key_passphrase)
    signature = key.sign(
        signed_query.encode("utf-8"),
        padding.PKCS1v15(),
        _hash_algorithm(signature_algorithm),
    )
    return base64.b64encode(signature).decode("ascii")


def _sign_xml(root: ET._Element, *, config: SAMLProviderConfig) -> ET._Element:
    _require_signing_material(config.private_key, config.signing_certificate)
    signature_method = _SIGNXML_SIGNATURE_METHODS.get(config.signature_algorithm)
    if signature_method is None:
        msg = f"unsupported SAML signature algorithm: {config.signature_algorithm}"
        raise RuntimeError(msg)
    digest_method = _SIGNXML_DIGEST_ALGORITHMS.get(config.digest_algorithm)
    if digest_method is None:
        msg = f"unsupported SAML digest algorithm: {config.digest_algorithm}"
        raise RuntimeError(msg)
    try:
        return XMLSigner(
            method=methods.enveloped,
            signature_algorithm=signature_method,
            digest_algorithm=digest_method,
            c14n_algorithm=CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0,
        ).sign(
            root,
            key=config.private_key.encode("utf-8"),
            passphrase=config.private_key_passphrase.encode("utf-8") if config.private_key_passphrase else None,
            cert=_certificate_to_pem(config.signing_certificate),
            reference_uri=f"#{root.attrib['ID']}",
            id_attribute="ID",
            always_add_key_value=False,
        )
    except Exception as exc:
        msg = "failed to sign SAML XML payload"
        raise RuntimeError(msg) from exc


def _require_signing_material(private_key: str | None, certificate: str | None) -> None:
    if private_key and certificate:
        return
    missing = "private_key" if not private_key else "signing_certificate"
    msg = f"SAML signing requires {missing}"
    raise RuntimeError(msg)


def _load_private_key(private_key: str | None, *, passphrase: str | None) -> types.PrivateKeyTypes:
    if private_key is None:
        msg = "SAML signing requires private_key"
        raise RuntimeError(msg)
    try:
        return serialization.load_pem_private_key(
            private_key.encode("utf-8"),
            password=passphrase.encode("utf-8") if passphrase else None,
        )
    except Exception as exc:
        msg = "failed to load SAML private key"
        raise RuntimeError(msg) from exc


def _verification_certificate(config: SAMLProviderConfig) -> str:
    if config.x509_certificate:
        return config.x509_certificate
    metadata = _metadata_values(config.idp_metadata_xml)
    if metadata.certificate is not None:
        return metadata.certificate
    msg = "SAML provider is missing x509_certificate"
    raise RuntimeError(msg)


def _resolved_sso_url(config: SAMLProviderConfig) -> str:
    if config.sso_url:
        return config.sso_url
    metadata = _metadata_values(config.idp_metadata_xml)
    if metadata.sso_url is not None:
        return metadata.sso_url
    msg = "SAML provider is missing sso_url"
    raise RuntimeError(msg)


def _resolved_idp_slo_url(config: SAMLProviderConfig) -> str:
    if config.slo_url:
        return config.slo_url
    metadata = _metadata_values(config.idp_metadata_xml)
    if metadata.slo_url is not None:
        return metadata.slo_url
    msg = "SAML provider is missing IdP slo_url"
    raise RuntimeError(msg)


def _decryption_key_manager(config: SAMLProviderConfig) -> xmlsec.KeysManager:
    if config.decryption_private_key is None:
        msg = "encrypted SAML assertions require decryption_private_key"
        raise RuntimeError(msg)
    try:
        key = xmlsec.Key.from_memory(
            config.decryption_private_key,
            xmlsec.constants.KeyDataFormatPem,
            config.decryption_private_key_passphrase,
        )
    except Exception as exc:
        msg = "failed to load SAML decryption private key"
        raise RuntimeError(msg) from exc
    manager = xmlsec.KeysManager()
    manager.add_key(key)
    return manager


@dataclass(slots=True, kw_only=True, frozen=True)
class _MetadataValues:
    sso_url: str | None = None
    slo_url: str | None = None
    certificate: str | None = None


def _metadata_values(metadata_xml: str | None) -> _MetadataValues:
    if not metadata_xml:
        return _MetadataValues()
    try:
        root = ET.fromstring(metadata_xml.encode("utf-8"), parser=_xml_parser())
    except ET.XMLSyntaxError:
        return _MetadataValues()
    sso_url = next(
        (
            element.attrib.get("Location")
            for element in root.iter()
            if _local_name(element.tag) == "SingleSignOnService" and element.attrib.get("Location")
        ),
        None,
    )
    slo_url = next(
        (
            element.attrib.get("Location")
            for element in root.iter()
            if _local_name(element.tag) == "SingleLogoutService" and element.attrib.get("Location")
        ),
        None,
    )
    certificate = next(
        (
            element.text.strip()
            for element in root.iter()
            if _local_name(element.tag) == "X509Certificate" and element.text and element.text.strip()
        ),
        None,
    )
    return _MetadataValues(sso_url=sso_url, slo_url=slo_url, certificate=certificate)


def _certificate_to_pem(certificate: str | None) -> str:
    if certificate is None:
        msg = "SAML certificate is required"
        raise RuntimeError(msg)
    normalized = certificate.strip()
    if "BEGIN CERTIFICATE" in normalized:
        return normalized
    return f"-----BEGIN CERTIFICATE-----\n{_certificate_body(normalized)}\n-----END CERTIFICATE-----"


def _certificate_body(certificate: str) -> str:
    normalized = "".join(
        line.strip()
        for line in certificate.strip().splitlines()
        if "BEGIN CERTIFICATE" not in line and "END CERTIFICATE" not in line
    )
    return "\n".join(textwrap.wrap(normalized, 64))


def _hash_algorithm(signature_algorithm: str) -> hashes.HashAlgorithm:
    if signature_algorithm == "rsa-sha256":
        return hashes.SHA256()
    if signature_algorithm == "rsa-sha384":
        return hashes.SHA384()
    if signature_algorithm == "rsa-sha512":
        return hashes.SHA512()
    msg = f"unsupported SAML signature algorithm: {signature_algorithm}"
    raise RuntimeError(msg)


def _has_direct_signature(element: ET._Element) -> bool:
    return element.find(f"./{_tag(_DS_NS, 'Signature')}") is not None


def _xml_parser() -> ET.XMLParser:
    return ET.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)


def _raw_query_value(request: Request, key: str) -> str | None:
    raw_query = request.scope.get("query_string", b"")
    query_text = raw_query.decode("utf-8") if isinstance(raw_query, bytes) else str(raw_query)
    for item in query_text.split("&"):
        if item == key:
            return ""
        if item.startswith(f"{key}="):
            return item.partition("=")[2]
    return None
