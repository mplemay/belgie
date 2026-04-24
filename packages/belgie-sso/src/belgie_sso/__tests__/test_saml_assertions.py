from __future__ import annotations

import base64
import textwrap

import pytest

from belgie_sso.saml import _parse_saml_message, _require_single_assertion

_MAX_BYTES = 65_536


def _encode(xml: str) -> str:
    return base64.b64encode(textwrap.dedent(xml).encode("utf-8")).decode("ascii")


def _parse_xml(xml: str):
    return _parse_saml_message(
        _encode(xml),
        max_bytes=_MAX_BYTES,
        payload_name="SAMLResponse",
        compressed=False,
    )


def test_parse_saml_message_accepts_base64_with_embedded_whitespace() -> None:
    xml = """
        <samlp:Response
            xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
            xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
        >
            <saml:Assertion ID="123">
                <saml:Subject><saml:NameID>user@example.com</saml:NameID></saml:Subject>
            </saml:Assertion>
        </samlp:Response>
    """
    payload = _encode(xml)
    wrapped_lf = "\n".join(textwrap.wrap(payload, 76))
    wrapped_crlf = "\r\n".join(textwrap.wrap(payload, 76))
    wrapped_spaces = " \t ".join(textwrap.wrap(payload, 20))

    for wrapped in (wrapped_lf, wrapped_crlf, wrapped_spaces):
        root = _parse_saml_message(
            wrapped,
            max_bytes=_MAX_BYTES,
            payload_name="SAMLResponse",
            compressed=False,
        )
        assertion = _require_single_assertion(root)
        assert assertion.attrib["ID"] == "123"


def test_require_single_assertion_rejects_responses_without_assertions() -> None:
    root = _parse_xml(
        """
        <samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">
            <samlp:Status>
                <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
            </samlp:Status>
        </samlp:Response>
        """,
    )

    with pytest.raises(RuntimeError, match="exactly one assertion"):
        _require_single_assertion(root)


def test_require_single_assertion_rejects_multiple_direct_assertions() -> None:
    root = _parse_xml(
        """
        <samlp:Response
            xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
            xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
        >
            <saml:Assertion ID="assertion-1"/>
            <saml:Assertion ID="assertion-2"/>
        </samlp:Response>
        """,
    )

    with pytest.raises(RuntimeError, match="exactly one assertion"):
        _require_single_assertion(root)


def test_require_single_assertion_rejects_assertion_in_extensions() -> None:
    root = _parse_xml(
        """
        <samlp:Response
            xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
            xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
        >
            <samlp:Extensions>
                <saml:Assertion ID="injected-assertion"/>
            </samlp:Extensions>
            <saml:Assertion ID="legitimate-assertion"/>
        </samlp:Response>
        """,
    )

    with pytest.raises(RuntimeError, match="exactly one assertion"):
        _require_single_assertion(root)


def test_require_single_assertion_rejects_deeply_nested_assertions() -> None:
    root = _parse_xml(
        """
        <samlp:Response
            xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
            xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
        >
            <Level1>
                <Level2>
                    <saml:Assertion ID="deep-injected"/>
                </Level2>
            </Level1>
            <saml:Assertion ID="legitimate-assertion"/>
        </samlp:Response>
        """,
    )

    with pytest.raises(RuntimeError, match="exactly one assertion"):
        _require_single_assertion(root)


def test_require_single_assertion_accepts_unprefixed_and_custom_prefixed_assertions() -> None:
    unprefixed = _parse_xml(
        """
        <Response>
            <Assertion ID="plain-assertion"/>
        </Response>
        """,
    )
    custom_prefixed = _parse_xml(
        """
        <custom:Response
            xmlns:custom="urn:oasis:names:tc:SAML:2.0:protocol"
            xmlns:myprefix="urn:oasis:names:tc:SAML:2.0:assertion"
        >
            <myprefix:Assertion ID="custom-assertion"/>
        </custom:Response>
        """,
    )

    assert _require_single_assertion(unprefixed).attrib["ID"] == "plain-assertion"
    assert _require_single_assertion(custom_prefixed).attrib["ID"] == "custom-assertion"


def test_parse_saml_message_rejects_invalid_base64() -> None:
    with pytest.raises(RuntimeError, match="invalid SAMLResponse encoding"):
        _parse_saml_message(
            "not-valid-base64!!!",
            max_bytes=_MAX_BYTES,
            payload_name="SAMLResponse",
            compressed=False,
        )


def test_parse_saml_message_rejects_invalid_xml() -> None:
    with pytest.raises(RuntimeError, match="invalid SAMLResponse XML"):
        _parse_saml_message(
            base64.b64encode(b"not valid xml").decode("ascii"),
            max_bytes=_MAX_BYTES,
            payload_name="SAMLResponse",
            compressed=False,
        )
