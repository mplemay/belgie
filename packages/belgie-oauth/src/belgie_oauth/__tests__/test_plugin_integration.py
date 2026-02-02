from belgie_core.core.belgie import Belgie
from belgie_oauth.plugin import OAuthPlugin
from belgie_oauth.settings import OAuthSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_oauth_plugin_registers_routes(belgie_instance: Belgie, oauth_settings: OAuthSettings) -> None:
    plugin = belgie_instance.add_plugin(OAuthPlugin, settings=oauth_settings)
    assert plugin in belgie_instance.plugins

    app = FastAPI()
    app.include_router(belgie_instance.router())

    with TestClient(app) as client:
        response = client.get("/auth/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
