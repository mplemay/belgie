from typing import NotRequired, TypedDict

from pydantic import SecretStr
from pydantic_settings import BaseSettings

from belgie.auth import Auth
from belgie.auth.providers.google import GoogleProviderSettings


class ProviderSettings(BaseSettings):
    client_id: str
    client_secret: SecretStr
    redirect_uri: str


class Providers(TypedDict, total=False):
    google: NotRequired[GoogleProviderSettings]


auth = Auth(providers={"google": GoogleProviderSettings(...)})
