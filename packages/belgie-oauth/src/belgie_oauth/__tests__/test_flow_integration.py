from urllib.parse import parse_qs, urlparse

from belgie_oauth.settings import OAuthSettings
from belgie_oauth.utils import create_code_challenge
from fastapi.testclient import TestClient


def test_full_oauth_flow(client: TestClient, oauth_settings: OAuthSettings) -> None:
    code_verifier = "verifier"
    code_challenge = create_code_challenge(code_verifier)

    authorize_response = client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": oauth_settings.client_id,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_challenge": code_challenge,
            "state": "flow-state",
        },
        follow_redirects=False,
    )

    assert authorize_response.status_code == 302
    login_location = authorize_response.headers["location"]
    assert "/auth/oauth/login" in login_location

    login_response = client.get(login_location)
    assert login_response.status_code == 200

    callback_response = client.post(
        "/auth/oauth/login/callback",
        data={
            "username": oauth_settings.demo_username,
            "password": oauth_settings.demo_password,
            "state": "flow-state",
        },
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    redirect_location = callback_response.headers["location"]
    code = parse_qs(urlparse(redirect_location).query)["code"][0]

    token_response = client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "code_verifier": code_verifier,
        },
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    access_token = token_payload["access_token"]

    introspect_response = client.post(
        "/auth/oauth/introspect",
        data={"token": access_token},
    )

    assert introspect_response.status_code == 200
    assert introspect_response.json()["active"] is True
