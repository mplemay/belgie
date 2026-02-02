from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fastapi import APIRouter

if TYPE_CHECKING:
    from belgie_core.core.belgie import Belgie


@runtime_checkable
class Plugin(Protocol):
    """Protocol for Belgie plugins."""

    def __init__(self, auth: "Belgie", *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the plugin.

        Args:
            auth: The parent Belgie instance.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        ...

    @property
    def router(self) -> APIRouter:
        """Return the FastAPI router for this plugin."""
        ...
