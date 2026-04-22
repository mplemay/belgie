from authlib.oauth2.base import OAuth2Error


class InvalidTargetError(OAuth2Error):
    error = "invalid_target"


class UnsupportedTokenTypeHintError(OAuth2Error):
    error = "invalid_request"
    description = "unsupported token_type_hint"
