"""World-boss lifecycle poller: one loop, fixed order, exponential backoff.

E2 design §4: the poller is the only automatic spawner. Each round first checks
``boss.enabled`` (and the domain catalog gate) — when disabled it skips spawning
but still dispatches pending outbox deliveries so committed events are not
stuck. When enabled it calls ``WorldBossService.ensure_spawn(None)`` (which
dissipates expired active rows before deciding) and then always calls
``WorldBossEventDispatcher.dispatch_pending``. Only this module knows the
backoff schedule; the domain service remains a pure state machine.

A regular round where the boss already terminated (defeated/dissipated) is a
*normal* state: ``ensure_spawn(None)`` rejects with ``WorldBossSpawnRejected``
until ``next_spawn_at``. The poller swallows that rejection instead of treating
it as a failure — otherwise the exponential backoff would also skip
``dispatch_pending`` for the whole respawn window and starve the outbox.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from astrbot.api import logger

from .world_boss_service import WorldBossSpawnRejected

# Backoff contract (E2 design §4): min(60 * 2**n, 3600) seconds.
BASE_RETRY_DELAY_SECONDS = 60
MAX_RETRY_DELAY_SECONDS = 3600
DEFAULT_POLL_INTERVAL_SECONDS = 60


class WorldBossPoller:
    """Drive world-boss spawning and outbox delivery on a background loop.

    Args:
        service: ``WorldBossService`` owning the spawn state machine.
        dispatcher: ``WorldBossEventDispatcher`` for committed events.
        is_enabled: Callable returning the live ``boss.enabled`` switch.
        interval_seconds: Healthy-round sleep between polls.
        ensure_connection: Optional database reconnect hook; scheduled tasks
            must re-check the connection before opening a round (AGENTS §3).
        sleep: Injectable sleep function (tests avoid real waiting).
    """

    def __init__(
        self,
        service: Any,
        dispatcher: Any,
        is_enabled: Callable[[], bool],
        *,
        interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        ensure_connection: Callable[[], Awaitable[None]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.service = service
        self.dispatcher = dispatcher
        self.is_enabled = is_enabled
        self.interval_seconds = max(1, int(interval_seconds))
        self.ensure_connection = ensure_connection
        self.sleep = sleep
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        """Whether the background task is currently scheduled."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Create the background task once (idempotent while running)."""
        if self.running:
            return
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        """Cancel the background task and wait for its cancellation to settle."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def poll_once(self) -> None:
        """Run exactly one lifecycle round in the contract order.

        Spawning is gated by ``is_enabled`` *and* the domain's catalog gate
        (``WorldBossService.enabled`` is false for a missing/legacy v1
        ``enemies.json``). Dispatch always runs so events that were committed
        before the switch flipped false still get delivered.

        A ``WorldBossSpawnRejected`` from the regular path only means the next
        respawn is not eligible yet (or the domain is disabled); it is a normal
        state, not a round failure. Rethrowing it would skip dispatch for the
        whole terminal window (12h/24h) and put the loop into backoff.
        """
        if self.ensure_connection is not None:
            await self.ensure_connection()
        if self.is_enabled() and bool(getattr(self.service, "enabled", True)):
            try:
                await self.service.ensure_spawn(None)
            except WorldBossSpawnRejected as exc:
                logger.debug("世界 Boss 本轮未生成：%s", exc)
        await self.dispatcher.dispatch_pending()

    async def run(self) -> None:
        """Loop ``poll_once`` with exponential backoff on failure."""
        failures = 0
        while True:
            try:
                await self.poll_once()
                failures = 0
                await self.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - background loop boundary
                delay = min(
                    BASE_RETRY_DELAY_SECONDS * (2**failures),
                    MAX_RETRY_DELAY_SECONDS,
                )
                failures += 1
                logger.error(
                    "世界 Boss 轮询异常，%s 秒后重试（第 %s 次）：%s",
                    delay,
                    failures,
                    exc,
                )
                await self.sleep(delay)


def retry_delay_seconds(failures: int) -> int:
    """Return the exponential backoff delay for a failure count.

    Args:
        failures: Number of consecutive failures *before* this retry.

    Returns:
        ``min(60 * 2**failures, 3600)`` seconds.
    """
    return min(
        BASE_RETRY_DELAY_SECONDS * (2 ** max(0, int(failures))), MAX_RETRY_DELAY_SECONDS
    )
