from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import APIRouter

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie


@runtime_checkable
class Plugin(Protocol):
    """Protocol for Belgie plugins."""

    def router(self, belgie: "Belgie") -> APIRouter:
        """Return the FastAPI router for this plugin."""
        ...

    def public(self, belgie: "Belgie") -> APIRouter:
        """Return the FastAPI router for public root-level routes."""
        ...
