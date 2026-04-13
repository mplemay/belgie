from belgie_core.core.belgie import Belgie
from belgie_oauth_server.settings import OAuthServer
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_oauth_plugin_registers_routes(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    plugin = belgie_instance.add_plugin(oauth_settings)
    assert plugin in belgie_instance.plugins

    app = FastAPI()
    app.include_router(belgie_instance.router)

    with TestClient(app) as client:
        response = client.get("/auth/oauth/.well-known/oauth-authorization-server")
        assert response.status_code == 200


def test_oauth_plugin_openapi_exposes_typed_response_models(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    belgie_instance.add_plugin(oauth_settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    schema = app.openapi()
    components = schema["components"]["schemas"]

    assert "OAuthServerToken" in components
    assert "OAuthServerIntrospectionResponse" in components
    assert "UserInfoResponse" in components

    token_schema = schema["paths"]["/auth/oauth/token"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    introspect_schema = schema["paths"]["/auth/oauth/introspect"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    userinfo_schema = schema["paths"]["/auth/oauth/userinfo"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]

    assert token_schema["$ref"] == "#/components/schemas/OAuthServerToken"
    assert introspect_schema["$ref"] == "#/components/schemas/OAuthServerIntrospectionResponse"
    assert userinfo_schema["$ref"] == "#/components/schemas/UserInfoResponse"
