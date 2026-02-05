import builtins
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

import belgie

_MISSING_ALCHEMY = "No module named 'belgie_alchemy'"
_MISSING_OAUTH_CLIENT = "No module named 'belgie_oauth'"


def test_alchemy_adapter_missing_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import_module(name: str):
        assert name == "belgie_alchemy"
        raise ModuleNotFoundError(_MISSING_ALCHEMY)

    monkeypatch.setattr(belgie, "import_module", fake_import_module)

    with pytest.raises(ImportError, match=r"belgie\[alchemy\]"):
        belgie.AlchemyAdapter  # noqa: B018


def test_alchemy_adapter_present(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubAdapter:
        pass

    stub_module = SimpleNamespace(AlchemyAdapter=StubAdapter)

    def fake_import_module(name: str):
        assert name == "belgie_alchemy"
        return stub_module

    monkeypatch.setattr(belgie, "import_module", fake_import_module)

    from belgie import AlchemyAdapter  # noqa: PLC0415

    assert AlchemyAdapter is StubAdapter


def test_oauth_client_missing_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fake_import(name: str, _globals=None, _locals=None, fromlist=(), level=0):
        if name == "belgie_oauth":
            raise ModuleNotFoundError(_MISSING_OAUTH_CLIENT)
        return original_import(name, _globals, _locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "belgie.oauth_client", raising=False)

    with pytest.raises(ImportError, match=r"belgie\[oauth-client\]"):
        importlib.import_module("belgie.oauth_client")


def test_oauth_client_present(monkeypatch: pytest.MonkeyPatch) -> None:
    class StubClient:
        pass

    class StubPlugin:
        pass

    class StubSettings:
        pass

    class StubUserInfo:
        pass

    stub_module = ModuleType("belgie_oauth")
    stub_module.GoogleOAuthClient = StubClient
    stub_module.GoogleOAuthPlugin = StubPlugin
    stub_module.GoogleOAuthSettings = StubSettings
    stub_module.GoogleUserInfo = StubUserInfo

    monkeypatch.setitem(sys.modules, "belgie_oauth", stub_module)
    monkeypatch.delitem(sys.modules, "belgie.oauth_client", raising=False)

    module = importlib.import_module("belgie.oauth_client")

    assert module.GoogleOAuthClient is StubClient
    assert module.GoogleOAuthPlugin is StubPlugin
    assert module.GoogleOAuthSettings is StubSettings
    assert module.GoogleUserInfo is StubUserInfo
