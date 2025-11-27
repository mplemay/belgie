"""Main trace orchestrator."""

from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.trace.adapters.protocols import TraceAdapterProtocol
from belgie.trace.core.client import TraceClient
from belgie.trace.core.settings import TraceSettings

if TYPE_CHECKING:
    from typing import Any


class _TraceCallable:
    """Descriptor that makes Trace instances callable with instance-specific dependencies.

    This allows Depends(trace) to work seamlessly - each Trace instance gets its own
    callable that has the adapter's database dependency baked into the signature.
    """

    def __get__(self, obj: "Any | None", objtype: "type | None" = None) -> "Any":  # noqa: ANN401
        """Return instance-specific callable when accessed through an instance."""
        if obj is None:
            # Accessed through class, return descriptor itself
            return self

        # Return a callable with this instance's adapter.dependency
        def __call__(  # noqa: N807
            db: AsyncSession | None = Depends(obj.adapter.dependency) if obj.adapter else None,  # noqa: B008
        ) -> TraceClient:
            return TraceClient(
                db=db,
                adapter=obj.adapter,
                settings=obj.settings,
            )

        return __call__


class Trace:
    """Main trace orchestrator for Belgie.

    The Trace class provides the foundational infrastructure for analytics and tracking.
    This is a minimal implementation that establishes the architecture pattern.
    Tracking functionality will be added incrementally.

    Attributes:
        settings: Trace configuration settings
        adapter: Optional database adapter for persistence operations

    Example:
        >>> from belgie.trace import Trace, TraceSettings
        >>>
        >>> settings = TraceSettings(enabled=True)
        >>> trace = Trace(settings=settings)
        >>> # Full tracking functionality will be added later
    """

    # Use descriptor to make each instance callable with its own dependency
    __call__ = _TraceCallable()

    def __init__(
        self,
        adapter: TraceAdapterProtocol | None = None,
        settings: TraceSettings | None = None,
    ) -> None:
        """Initialize the Trace instance.

        Args:
            adapter: Optional database adapter (will be required when implementing tracking)
            settings: Trace configuration settings
        """
        self.adapter = adapter
        self.settings = settings or TraceSettings()
