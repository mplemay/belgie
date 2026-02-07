from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import APIRouter

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings


@runtime_checkable
class Plugin[S](Protocol):
    """Protocol for Belgie plugins."""

    def __init__(self, belgie_settings: "BelgieSettings", settings: S) -> None:
        """Initialize plugin with Belgie settings and plugin settings."""
        ...

    def router(self, belgie: "Belgie") -> APIRouter | None:
        """Return the FastAPI router for this plugin."""
        ...

    def public(self, belgie: "Belgie") -> APIRouter | None:
        """Return the FastAPI router for public root-level routes."""
        ...
