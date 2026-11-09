"""World-boss post-commit events: renderer + outbox dispatcher (child D).

The domain transaction only appends *one* business event per transition
(prd R7); this module turns those events into per-destination deliveries and
performs the actual send strictly **outside** any database transaction
(design §5).

Narrative authority is the instance birth snapshot only: the renderer reads
the five copy strings and narrative_approved from the snapshot persisted at
spawn time. It never reads narrative_config.json / copy_variants.csv and
never falls back to code copy; an unapproved profile renders None and the
delivery is parked as uncertain (never broadcast).

The outbox is at-least-once by design (no exactly-once guarantee):

- queued deliveries are claimed conditionally (claim_delivery only accepts
  queued rows whose retry watermark passed) and retried while the sender
  raises a *known* failure.
- an ambiguous send (raised DeliveryUncertain) is parked as uncertain and
  never auto-retried; the same applies once max_attempts is exhausted.
- events committed without deliveries (crash between commit and expansion) are
  recovered by scanning a fixed recent window - business_events has no
  expansion-complete column and the schema is frozen (prd R7).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

from astrbot.api import logger

try:
    from ..data.pve_repository import OutboxRepository, WorldBossRepository
except ImportError:
    # Standalone (tests) fallback: load by file path, same idiom as other managers.
    def _load_module(name, rel_path):
        """Import a plugin module by file path so this file can run standalone."""
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(plugin_root, rel_path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    _pr = _load_module("pve_repository", "data/pve_repository.py")
    OutboxRepository = _pr.OutboxRepository
    WorldBossRepository = _pr.WorldBossRepository

# prd R7 event vocabulary. One business event per domain transition; the
# business key is derived from the transition identity so a replayed commit
# can never insert a second event.
EVENT_SPAWN = "world_boss_spawn"
EVENT_STAGE = "world_boss_stage"
EVENT_DEFEATED = "world_boss_defeated"
EVENT_DISSIPATED = "world_boss_dissipated"
EVENT_TYPES = frozenset({EVENT_SPAWN, EVENT_STAGE, EVENT_DEFEATED, EVENT_DISSIPATED})
AGGREGATE_TYPE = "world_boss_instance"

# stage 事件的文案键由阶段决定（prd R7 五列映射）。
COPY_KEY_BY_PHASE = {2: "phase2_text", 3: "phase3_text"}

DEFAULT_RECOVERY_WINDOW_SECONDS = 600
DEFAULT_LEASE_SECONDS = 60
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 60


class DeliveryUncertain(RuntimeError):
    """The send may or may not have reached the platform.

    Raise this from a sender adapter when the transport outcome is genuinely
    unknown (timeout after the request was written, ambiguous response). The
    dispatcher parks such deliveries as uncertain and never auto-retries them:
    replaying an already-sent message is worse than a manual retry.
    """


# ----------------------------------------------------------------------
# business keys (unique per domain transition; prd R7 idempotency)
# ----------------------------------------------------------------------


def spawn_business_key(instance_id: str) -> str:
    """Business key of the spawn event of one instance."""
    return f"world_boss:spawn:{instance_id}"


def stage_business_key(instance_id: str, phase: int) -> str:
    """Business key of the phase-transition event of one instance."""
    return f"world_boss:stage:{instance_id}:{int(phase)}"


def defeated_business_key(instance_id: str) -> str:
    """Business key of the defeated event of one instance."""
    return f"world_boss:defeated:{instance_id}"


def dissipated_business_key(instance_id: str) -> str:
    """Business key of the dissipated event of one instance."""
    return f"world_boss:dissipated:{instance_id}"


# ----------------------------------------------------------------------
# renderer (birth snapshot only, approved-only)
# ----------------------------------------------------------------------


def _json_object(raw: Any) -> dict | None:
    """Parse a JSON object stored as text; None if unusable."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def render_event_text(event: dict | None, instance: dict | None) -> str | None:
    """Render the broadcast text of one event from immutable spawn facts.

    Args:
        event: business_events row (payload still JSON text).
        instance: world_boss_instances row the event belongs to.

    Returns:
        The copy string persisted in the birth snapshot, or None when the event
        must not be broadcast (unknown event, unapproved narrative, missing
        copy key, empty text). None is a legal, permanent outcome - never
        replaced by a code fallback.
    """
    if not event or not instance:
        return None
    if event.get("event_type") not in EVENT_TYPES:
        return None
    if event.get("aggregate_type") not in (None, "", AGGREGATE_TYPE):
        return None
    snapshot = _json_object(instance.get("birth_snapshot"))
    if snapshot is None:
        return None
    if not bool(snapshot.get("narrative_approved", False)):
        return None
    payload = _json_object(event.get("payload")) or {}
    copy_key = payload.get("copy_key")
    if not isinstance(copy_key, str) or not copy_key:
        return None
    text = snapshot.get(copy_key)
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip()


# ----------------------------------------------------------------------
# dispatcher
# ----------------------------------------------------------------------


class WorldBossEventDispatcher:
    """Expand committed events into deliveries and send them outside transactions.

    Args:
        db: DataBase instance (repository seam over db.conn).
        sender: async callable(platform, group_id, text) performing the real
            send; must raise DeliveryUncertain when the outcome is unknown and
            another exception when the send is known to have failed.
        targets: Callable (or sequence) returning (platform, group_id) pairs -
            the destination snapshot taken when the event is expanded.
        clock: Injectable business clock (unix seconds).
        recovery_window_seconds: Fixed window for the "committed but not
            expanded" recovery scan (prd R7: no config item, no schema change).
        lease_seconds: Claim lease length handed to claim_delivery.
        max_attempts: Attempt cap; exhausted deliveries become uncertain.
        retry_backoff_seconds: Linear backoff unit for known failures.
        owner: Dispatcher identity written into claim_owner.
    """

    def __init__(
        self,
        db: Any,
        *,
        sender: Callable[[str, str, str], Any],
        targets: Callable[[], Sequence[tuple[str, str]]] | Sequence[tuple[str, str]],
        clock: Callable[[], float] = time.time,
        recovery_window_seconds: int = DEFAULT_RECOVERY_WINDOW_SECONDS,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: int = DEFAULT_RETRY_BACKOFF_SECONDS,
        owner: str = "world_boss_dispatcher",
    ) -> None:
        self.db = db
        self.sender = sender
        self.targets = targets
        self.clock = clock
        self.recovery_window_seconds = int(recovery_window_seconds)
        self.lease_seconds = int(lease_seconds)
        self.max_attempts = int(max_attempts)
        self.retry_backoff_seconds = int(retry_backoff_seconds)
        self.owner = owner

    @property
    def outbox(self) -> OutboxRepository:
        """Outbox repository bound to the live connection (reconnect-safe)."""
        return OutboxRepository(self.db.conn)

    @property
    def instances(self) -> WorldBossRepository:
        """Instance repository bound to the live connection (reconnect-safe)."""
        return WorldBossRepository(self.db.conn)

    def _now(self, now: int | None) -> int:
        """Resolve the business timestamp for this call."""
        return int(now) if now is not None else int(self.clock())

    def _destinations(self) -> list[tuple[str, str]]:
        """Snapshot the destination list (callable or static sequence)."""
        raw = self.targets() if callable(self.targets) else self.targets
        return [(str(platform), str(group_id)) for platform, group_id in raw or ()]

    async def expand(self, event_id: str, *, now: int | None = None) -> int:
        """Expand one event into per-destination deliveries (idempotent).

        Args:
            event_id: Business event to expand.
            now: Business timestamp override.

        Returns:
            Number of newly created deliveries (0 on replay / unknown event).
        """
        stamp = self._now(now)
        event = await self.outbox.get_event(event_id)
        if event is None or event["event_type"] not in EVENT_TYPES:
            return 0
        created_count = 0
        for platform, group_id in self._destinations():
            _, created = await self.outbox.add_delivery(
                event_id=event_id, platform=platform, group_id=group_id, now=stamp
            )
            created_count += int(bool(created))
        return created_count

    async def dispatch_pending(
        self, *, now: int | None = None, limit: int = 50
    ) -> dict[str, int]:
        """Recover unexpanded events, then send all claimable deliveries.

        Args:
            now: Business timestamp override.
            limit: Row cap for both the recovery scan and the delivery scan.

        Returns:
            Counters expanded / sent / retried / uncertain.
        """
        stamp = self._now(now)
        summary = {"expanded": 0, "sent": 0, "retried": 0, "uncertain": 0}

        # 1) Recovery scan: committed events with no delivery rows at all.
        #    Idempotent by construction - expansion is UNIQUE(event, platform, group).
        for event in await self.outbox.list_events_since(
            occurred_at_from=stamp - self.recovery_window_seconds, limit=limit
        ):
            if event["event_type"] not in EVENT_TYPES:
                continue
            if await self.outbox.list_deliveries_for_event(event["event_id"]):
                continue
            summary["expanded"] += await self.expand(event["event_id"], now=stamp)

        # 2) Dispatch: claim each due delivery, send outside the DB, then record
        #    the outcome. A failed destination never replays an already sent one.
        for delivery in await self.outbox.list_deliveries(now=stamp, limit=limit):
            event = await self.outbox.get_event(delivery["event_id"])
            if event is None or event["event_type"] not in EVENT_TYPES:
                continue
            claimed = await self.outbox.claim_delivery(
                int(delivery["delivery_id"]),
                owner=self.owner,
                lease_until=stamp + self.lease_seconds,
                now=stamp,
            )
            if claimed is None:
                continue
            outcome = await self._deliver(claimed, now=stamp)
            summary[outcome] += 1
        return summary

    async def _deliver(self, delivery: dict, *, now: int) -> str:
        """Send one claimed delivery and record its terminal state.

        Args:
            delivery: Delivery row returned by claim_delivery (dispatching).
            now: Business timestamp.

        Returns:
            sent / retried / uncertain.
        """
        event = await self.outbox.get_event(delivery["event_id"])
        instance = None
        if event is not None and event.get("aggregate_type") == AGGREGATE_TYPE:
            instance = await self.instances.get_instance(event["aggregate_id"])
        text = render_event_text(event, instance)
        if text is None:
            await self._complete(
                delivery,
                "uncertain",
                now=now,
                error="事件文案未批准或缺失，禁止广播",
            )
            return "uncertain"
        try:
            await self.sender(delivery["platform"], delivery["group_id"], text)
        except DeliveryUncertain as exc:
            await self._complete(
                delivery, "uncertain", now=now, error=f"发送结果不确定：{exc}"
            )
            return "uncertain"
        except Exception as exc:  # noqa: BLE001 - transport boundary
            attempts = int(delivery.get("attempt_count") or 0)
            if attempts >= self.max_attempts:
                await self._complete(
                    delivery,
                    "uncertain",
                    now=now,
                    error=f"连续 {attempts} 次发送失败：{exc}",
                )
                return "uncertain"
            retry_at = now + self.retry_backoff_seconds * max(1, attempts)
            await self._complete(
                delivery,
                "queued",
                now=now,
                error=f"发送失败，稍后重试：{exc}",
                retry_at=retry_at,
            )
            return "retried"
        await self._complete(delivery, "sent", now=now)
        return "sent"

    async def _complete(
        self,
        delivery: dict,
        state: str,
        *,
        now: int,
        error: str = "",
        retry_at: int = 0,
    ) -> None:
        """Apply one delivery transition guarded by the claim (owner + version)."""
        applied = await self.outbox.complete_delivery(
            int(delivery["delivery_id"]),
            owner=self.owner,
            expected_cas_version=int(delivery["cas_version"]),
            state=state,
            now=now,
            error=error,
            retry_at=retry_at,
        )
        if not applied:
            logger.warning(
                "世界 Boss 事件投递状态更新失败（租约被接管）：delivery_id=%s state=%s",
                delivery.get("delivery_id"),
                state,
            )
