from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

from fastapi import APIRouter

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie

SettingsT_contra = TypeVar("SettingsT_contra", contravariant=True)


@runtime_checkable
class Plugin[SettingsT_contra](Protocol):
    """Protocol for Belgie plugins."""

    def __init__(self, belgie: "Belgie", settings: SettingsT_contra) -> None:
        """Initialize the plugin.

        Args:
            belgie: The parent Belgie instance.
            settings: The plugin-specific settings.
        """
        ...

    @property
    def router(self) -> APIRouter:
        """Return the FastAPI router for this plugin."""
        ...
