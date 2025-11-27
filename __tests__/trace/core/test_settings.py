import pytest

from belgie.trace.core.settings import TraceSettings


def test_trace_settings_defaults() -> None:
    settings = TraceSettings()

    assert settings.enabled is True


def test_trace_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_TRACE_ENABLED", "false")

    settings = TraceSettings()

    assert settings.enabled is False


def test_trace_settings_custom_values() -> None:
    settings = TraceSettings(enabled=False)

    assert settings.enabled is False


def test_trace_settings_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("belgie_trace_enabled", "false")

    settings = TraceSettings()

    assert settings.enabled is False
