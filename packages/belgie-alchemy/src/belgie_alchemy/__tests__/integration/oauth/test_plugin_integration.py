from belgie_core.core.belgie import Belgie
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.settings import OAuthServerSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_oauth_plugin_registers_routes(
    belgie_instance: Belgie,
    oauth_settings: OAuthServerSettings,
) -> None:
    plugin = belgie_instance.add_plugin(OAuthServerPlugin, oauth_settings)
    assert plugin in belgie_instance.plugins

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        response = client.get("/auth/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200
