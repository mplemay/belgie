from types import SimpleNamespace

import pytest

import belgie

_MISSING_ALCHEMY = "No module named 'belgie_alchemy'"


def test_alchemy_adapter_missing_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import_module(name: str):
        assert name == "belgie_alchemy"
        raise ModuleNotFoundError(_MISSING_ALCHEMY)

    monkeypatch.setattr(belgie, "import_module", fake_import_module)

    with pytest.raises(ImportError, match=r"belgie\[alchemy\]"):
        pass


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
