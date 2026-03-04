from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import APIRouter

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings


@runtime_checkable
class PluginClient(Protocol):
    """Protocol for Belgie runtime plugins."""

    def router(self, belgie: "Belgie") -> APIRouter | None:
        """Return the FastAPI router for this plugin."""
        ...

    def public(self, belgie: "Belgie") -> APIRouter | None:
        """Return the FastAPI router for public root-level routes."""
        ...


@runtime_checkable
class Plugin[P: PluginClient](Protocol):
    """Protocol for Belgie plugin configuration callables."""

    def __call__(self, belgie_settings: "BelgieSettings") -> P:
        """Build and return a runtime plugin."""
        ...
