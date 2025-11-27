"""Trace client for request-scoped operations."""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from belgie.trace.adapters.protocols import TraceAdapterProtocol
from belgie.trace.core.settings import TraceSettings


@dataclass(frozen=True, slots=True, kw_only=True)
class TraceClient:
    """Client for trace operations with injected database session.

    This class provides trace operations with a captured database session,
    allowing for convenient operations without explicitly passing db to each method.

    Typically obtained via Trace.__call__() as a FastAPI dependency:
        client: TraceClient = Depends(trace)

    Attributes:
        db: Optional database session (will be required when implementing tracking)
        adapter: Optional adapter instance (will be required when implementing tracking)
        settings: Trace configuration settings

    Note:
        Methods for tracking functionality will be added as features are implemented.
    """

    db: AsyncSession | None = None
    adapter: TraceAdapterProtocol | None = None
    settings: TraceSettings = field(default_factory=TraceSettings)
