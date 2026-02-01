"""Generic database connection protocol for auth module.

This module defines the minimal interface required for database operations
in the auth module, allowing different database backends to be used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    type DBConnection = AsyncSession
else:

    @runtime_checkable
    class DBConnection(Protocol):
        """Generic database connection protocol.

        This protocol defines the minimal interface required for database operations
        in the auth module. It focuses on transaction management, as query execution
        is adapter-specific and varies by database backend.

        Different database backends implement this protocol naturally:
        - SQLAlchemy: AsyncSession implements this directly
        - asyncpg: Connection can be wrapped to provide these methods
        - MongoDB: ClientSession implements similar semantics

        Adapters should internally cast DBConnection to their specific type
        for query operations (e.g., cast to AsyncSession for SQLAlchemy).

        Example:
            >>> # SQLAlchemy AsyncSession naturally implements DBConnection
            >>> from sqlalchemy.ext.asyncio import AsyncSession
            >>> async def use_db(db: DBConnection) -> None:
            ...     # db can be any connection type implementing the protocol
            ...     await db.commit()
        """

        async def commit(self) -> None:
            """Commit the current transaction.

            Persists all changes made during this transaction to the database.
            Different backends may have different transaction semantics.

            Raises:
                Exception: Database-specific errors during commit
            """
            ...

        async def rollback(self) -> None:
            """Rollback the current transaction.

            Discards all changes made during this transaction. The database
            state is restored to the beginning of the transaction.

            Raises:
                Exception: Database-specific errors during rollback
            """
            ...

        async def close(self) -> None:
            """Close the connection/session.

            Releases database resources associated with this connection.
            May be a no-op for pooled connections that are managed externally.

            Raises:
                Exception: Database-specific errors during close
            """
            ...
