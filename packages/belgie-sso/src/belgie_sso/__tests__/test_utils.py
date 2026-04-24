from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from belgie_sso.utils import (
    choose_best_domain_match,
    deserialize_oidc_config,
    deserialize_saml_config,
    extract_email_domain,
    normalize_provider_domain_value,
    split_provider_domains,
)


@dataclass(frozen=True, slots=True)
class _Provider:
    id: UUID
    domain: str


def _email_matches_provider_domain(email: str, provider_domain: str) -> bool:
    if not (domain := extract_email_domain(email)):
        return False
    provider = _Provider(id=uuid4(), domain=normalize_provider_domain_value(provider_domain))
    return choose_best_domain_match(domain=domain, domains=[provider]) is not None


def test_email_domain_matching_accepts_exact_domains_case_insensitively() -> None:
    assert _email_matches_provider_domain("user@company.com", "company.com") is True
    assert _email_matches_provider_domain("USER@COMPANY.COM", "COMPANY.COM") is True


def test_email_domain_matching_accepts_subdomains() -> None:
    assert _email_matches_provider_domain("user@hr.company.com", "company.com") is True
    assert _email_matches_provider_domain("user@dept.hr.company.com", "company.com") is True


def test_email_domain_matching_rejects_suffix_lookalikes_and_invalid_emails() -> None:
    assert _email_matches_provider_domain("user@notcompany.com", "company.com") is False
    assert _email_matches_provider_domain("usercompany.com", "company.com") is False
    assert _email_matches_provider_domain("", "company.com") is False


def test_email_domain_matching_supports_multiple_domains_and_ignores_empty_segments() -> None:
    domains = "company.com, subsidiary.com ,, acquired-company.com"

    assert _email_matches_provider_domain("user@company.com", domains) is True
    assert _email_matches_provider_domain("user@dept.subsidiary.com", domains) is True
    assert _email_matches_provider_domain("user@acquired-company.com", domains) is True
    assert _email_matches_provider_domain("user@other.com", domains) is False
    assert split_provider_domains(normalize_provider_domain_value(domains)) == (
        "company.com",
        "subsidiary.com",
        "acquired-company.com",
    )


def test_deserialize_oidc_config_defaults_to_enterprise_scopes_when_missing() -> None:
    config = deserialize_oidc_config(
        {
            "issuer": "https://idp.example.com",
            "client_id": "client-id",
            "client_secret": "client-secret",
        },
    )

    assert config.scopes == ("openid", "email", "profile", "offline_access")


def test_deserialize_saml_config_defaults_to_idp_initiated_signin_for_legacy_records() -> None:
    config = deserialize_saml_config(
        {
            "entity_id": "urn:acme:sp",
            "sso_url": "https://idp.example.com/sso",
            "x509_certificate": "certificate",
        },
    )

    assert config.allow_idp_initiated is True


def test_deserialize_saml_config_preserves_optional_null_fields_for_metadata_only_records() -> None:
    config = deserialize_saml_config(
        {
            "entity_id": "urn:acme:sp",
            "sso_url": None,
            "x509_certificate": None,
            "idp_metadata_xml": "  <EntityDescriptor/>  ",
        },
    )

    assert config.sso_url is None
    assert config.x509_certificate is None
    assert config.idp_metadata_xml == "<EntityDescriptor/>"
