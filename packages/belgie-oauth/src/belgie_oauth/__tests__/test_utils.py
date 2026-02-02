from belgie_oauth.utils import construct_redirect_uri, create_code_challenge, join_url


def test_construct_redirect_uri_merges_params() -> None:
    uri = construct_redirect_uri("http://example.com/callback?foo=bar", code="abc", state="xyz")
    assert "foo=bar" in uri
    assert "code=abc" in uri
    assert "state=xyz" in uri


def test_join_url_handles_slashes() -> None:
    assert join_url("http://example.com/base/", "/authorize") == "http://example.com/base/authorize"
    assert join_url("http://example.com/base", "authorize") == "http://example.com/base/authorize"
    assert join_url("http://example.com/base", "") == "http://example.com/base"


def test_create_code_challenge_matches_rfc_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert create_code_challenge(verifier) == expected
