"""Connection-level ownership for standalone database leaf writes."""

import asyncio
from functools import wraps
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


class TxnState:
    """One-shot abort flag shared by all layers of one transaction."""

    def __init__(self):
        self.aborted = False


class _LeafWriteCM:
    """Own or join a connection transaction around a complete leaf write."""

    def __init__(self, conn: "aiosqlite.Connection", immediate: bool):
        self._conn = conn
        self._immediate = immediate
        self._condition: asyncio.Condition | None = None
        self._state: TxnState | None = None
        self._joined = False

    async def __aenter__(self) -> "_LeafWriteCM":
        """Claim ownership before the first DML or explicit BEGIN.

        Returns:
            The active leaf context.

        Raises:
            RuntimeError: If called without a running asyncio task.
        """
        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("leaf_write() requires a running asyncio task")
        conn = self._conn
        condition = getattr(conn, "_txn_free", None)
        if condition is None:
            # Bare connections in legacy tests lazily get the same ownership
            # fields that DataBase.connect() installs on managed connections.
            condition = asyncio.Condition()
            conn._txn_free = condition
        self._condition = condition
        if getattr(conn, "_txn_owner_task", None) is current_task:
            conn._txn_depth += 1
            self._joined = True
            self._state = conn._txn_state
            return self

        async with condition:
            while getattr(conn, "_txn_owner_task", None) is not None:
                await condition.wait()
            conn._txn_owner_task = current_task
            conn._txn_depth = 1
            conn._txn_state = TxnState()
            self._state = conn._txn_state
        try:
            if self._immediate and not conn.in_transaction:
                await conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            # BEGIN failure/cancellation must not strand the connection owner.
            async with condition:
                conn._txn_depth = 0
                conn._txn_owner_task = None
                conn._txn_state = None
                condition.notify_all()
            try:
                await conn.rollback()
            except Exception:
                pass
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Commit or roll back only as owner, then release all waiters."""
        conn = self._conn
        if self._joined:
            conn._txn_depth = max(0, conn._txn_depth - 1)
            return False
        try:
            if exc_type is not None or (self._state and self._state.aborted):
                await conn.rollback()
            else:
                try:
                    await conn.commit()
                except BaseException:
                    try:
                        await conn.rollback()
                    except Exception:
                        pass
                    raise
        finally:
            assert self._condition is not None
            async with self._condition:
                conn._txn_depth = 0
                conn._txn_owner_task = None
                conn._txn_state = None
                self._condition.notify_all()
        return False


def leaf_write(
    conn: "aiosqlite.Connection", *, immediate: bool = False
) -> _LeafWriteCM:
    """Return a connection-owned context for a complete leaf write.

    Same-task callers join the current owner. Cross-task callers wait before
    their first DML. ``immediate=True`` preserves existing read-modify-write
    leaves that require BEGIN IMMEDIATE; the default keeps sqlite's implicit
    BEGIN and raw hand-BEGIN compatibility.

    Args:
        conn: The aiosqlite connection carrying transaction ownership.
        immediate: Whether a standalone owner should issue BEGIN IMMEDIATE.

    Returns:
        The asynchronous leaf-write context manager.
    """
    return _LeafWriteCM(conn, immediate)


def leaf_write_method(*, immediate: bool = False):
    """Decorate an instance method whose entire body is one leaf write.

    The connection is read from ``self.conn``, ``self.db.conn`` or
    ``self._db.conn`` at call time, so reconnects never leave a cached
    connection in the decorator. This keeps the mechanical migration of small
    CRUD methods narrow while using exactly the same ownership context as
    explicit ``async with leaf_write(...)``.

    Args:
        immediate: Whether a standalone owner should issue BEGIN IMMEDIATE.

    Returns:
        An async method decorator applying the leaf ownership boundary.
    """

    def decorator(func):
        """Wrap one async instance method with connection ownership."""

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            """Resolve the current connection and run the method as a leaf."""
            conn = getattr(self, "conn", None)
            if conn is None:
                db = getattr(self, "db", None) or getattr(self, "_db", None)
                conn = db.conn
            async with leaf_write(conn, immediate=immediate):
                return await func(self, *args, **kwargs)

        return wrapper

    return decorator
