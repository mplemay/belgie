from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

from fastapi import APIRouter

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie

SettingsT = TypeVar("SettingsT", contravariant=True)  # noqa: PLC0105


@runtime_checkable
class Plugin[SettingsT](Protocol):
    """Protocol for Belgie plugins."""

    def __init__(self, belgie: "Belgie", settings: SettingsT) -> None:
        """Initialize the plugin.

        Args:
            belgie: The parent Belgie instance.
            settings: The plugin-specific settings.
        """
        ...

    def router(self) -> APIRouter:
        """Return the FastAPI router for this plugin."""
        ...
