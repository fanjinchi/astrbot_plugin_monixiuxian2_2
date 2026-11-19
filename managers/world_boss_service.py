"""World-boss domain service: fixed lifecycle + atomic challenges (child D).

One service owns the whole world-boss domain state machine (design §3):

- spawn: pick one of the four fixed profiles (random across all segments for
  the regular path, or an explicit GM-forced profile), freeze the birth
  snapshot, derive the instance id deterministically from
  (profile_id, spawn_epoch), and keep at most one active instance;
- lifecycle: active -> defeated (12h to respawn) | dissipated (24h to respawn);
  next_spawn_at is the single respawn-eligibility authority written together
  with terminated_at in the same CAS commit;
- challenge: a short transaction settles health and reads the instance
  snapshot, the deterministic fight runs *outside* any transaction (fixed RNG
  seeded from the challenge id), then one short transaction re-validates and
  applies, in fixed order, instance CAS -> daily attempt -> player health CAS ->
  challenge row / ledger / contribution / phase + terminal events. Any False
  aborts the whole unit of work (prd R4);
- events: the domain transaction only appends unique business events; the
  dispatcher in managers/world_boss_events.py expands and sends them after
  commit.

E2 owns activation: the lifecycle poller, handlers, outbox dispatcher wiring and
the dummy legacy-Boss removal live outside this service. ``get_active`` is the
query seam used by the ``世界Boss`` command (expiry settles, no spawn).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger

try:
    from ..data.pve_repository import (
        OutboxRepository,
        WorldBossRepository,
        shanghai_date_key,
    )
    from ..models import Player
    from .enemy_catalog import EnemyCatalog, WorldBossProfile, build_enemy_fighter
    from .enemy_manager import Enemy
    from .world_boss_events import (
        AGGREGATE_TYPE,
        COPY_KEY_BY_PHASE,
        EVENT_DEFEATED,
        EVENT_DISSIPATED,
        EVENT_SPAWN,
        EVENT_STAGE,
        defeated_business_key,
        dissipated_business_key,
        spawn_business_key,
        stage_business_key,
    )
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

    Player = None
    _pr = _load_module("pve_repository", "data/pve_repository.py")
    OutboxRepository = _pr.OutboxRepository
    WorldBossRepository = _pr.WorldBossRepository
    shanghai_date_key = _pr.shanghai_date_key
    _cat = _load_module("enemy_catalog", "managers/enemy_catalog.py")
    EnemyCatalog = _cat.EnemyCatalog
    WorldBossProfile = _cat.WorldBossProfile
    build_enemy_fighter = _cat.build_enemy_fighter
    _em = _load_module("enemy_manager", "managers/enemy_manager.py")
    Enemy = _em.Enemy
    _ev = _load_module("world_boss_events", "managers/world_boss_events.py")
    AGGREGATE_TYPE = _ev.AGGREGATE_TYPE
    COPY_KEY_BY_PHASE = _ev.COPY_KEY_BY_PHASE
    EVENT_DEFEATED = _ev.EVENT_DEFEATED
    EVENT_DISSIPATED = _ev.EVENT_DISSIPATED
    EVENT_SPAWN = _ev.EVENT_SPAWN
    EVENT_STAGE = _ev.EVENT_STAGE
    defeated_business_key = _ev.defeated_business_key
    dissipated_business_key = _ev.dissipated_business_key
    spawn_business_key = _ev.spawn_business_key
    stage_business_key = _ev.stage_business_key

# GM「时间快进」覆盖条目（openspec change: gm-time-skip-registry）：领域属主
# 声明即覆盖，只前移参与到期/冷却判定的时间戳。由 core/time_skip_registry.py
# 的 _PROVIDER_MODULES 汇总；E2 激活后世界 Boss 是这两个冷却域的唯一属主。
TIME_SKIP_ENTRIES: tuple[tuple[str, str], ...] = (
    (
        "世界Boss实例到期时间",
        "UPDATE world_boss_instances "
        "SET expires_at = expires_at - ? "
        "WHERE state = 'active' AND expires_at > 0",
    ),
    (
        "世界Boss下次再生时间",
        "UPDATE world_boss_instances "
        "SET next_spawn_at = next_spawn_at - ? "
        "WHERE next_spawn_at > 0",
    ),
)

INSTANCE_STATE_ACTIVE = "active"
INSTANCE_STATE_DEFEATED = "defeated"
INSTANCE_STATE_DISSIPATED = "dissipated"

SEGMENTS = ("练气", "筑基", "金丹", "元婴")

# Fallbacks only used when a frozen snapshot lost a field (should not happen for
# a validated catalog); the values mirror design_docs/content-design/world_bosses.csv.
DEFAULT_LIFETIME_H = 48
DEFAULT_DAILY_ATTEMPTS = 3
DEFAULT_RESPAWN_KILL_H = 12
DEFAULT_RESPAWN_DISSIPATE_H = 24
DEFAULT_PHASE_THRESHOLDS = (0.6, 0.2)
DEFAULT_PHASE2_DAMAGE_MULT = 1.10
DEFAULT_PHASE3_DAMAGE_MULT = 0.90
DEFAULT_PHASE3_ARMOR_MULT = 0.50

# prd R4: the busy template is part of the domain contract (E2 handler reuses it).
BUSY_TEMPLATE = "❌ 你当前正忙，无法挑战Boss！"

CHALLENGE_OUTCOME_DEFEATED = "defeated"
CHALLENGE_OUTCOME_ONGOING = "ongoing"

# Bounded conflict retries: a CAS loser recomputes the same deterministic fight
# against the fresh snapshot instead of replaying it against new HP (prd R4).
DEFAULT_MAX_CONFLICT_RETRIES = 3


class WorldBossSpawnRejected(RuntimeError):
    """A spawn request was refused; the message is user-facing Chinese."""


def _requested_profile_name(service: WorldBossService, profile_id: str) -> str:
    """Resolve a requested profile id to its display name when possible.

    Args:
        service: World-boss service whose catalog owns the profiles.
        profile_id: Requested catalog id (may be unknown).

    Returns:
        Catalog name when known, otherwise the raw id.
    """
    catalog = getattr(service, "catalog", None)
    lookup = getattr(catalog, "world_boss_by_id", None)
    if callable(lookup):
        try:
            return lookup(profile_id).name
        except Exception:  # noqa: BLE001 - unknown id falls back to raw text
            return profile_id
    return profile_id


async def spawn_with_message(
    service: WorldBossService, profile_id: str | None = None
) -> tuple[bool, str]:
    """Run ``ensure_spawn`` and render the shared management-entry message.

    Both management entry points (top-level ``生成Boss`` and ``GM 生成Boss``)
    must render the same three D-R1 branches: created, reused existing active
    instance, or a user-readable rejection. Only these entries may pass a
    ``profile_id``; the poller always uses ``None``.

    Args:
        service: World-boss domain service.
        profile_id: Optional forced profile id.

    Returns:
        (success, user-facing message). Failures are logged, never raised.
    """
    if service is None:
        return False, "❌ 世界 Boss 服务未初始化！"
    try:
        instance, created, resolved_profile_id = await service.ensure_spawn(profile_id)
    except WorldBossSpawnRejected as exc:
        return False, str(exc)
    except Exception:  # noqa: BLE001 - management entry must not crash
        logger.exception("世界 Boss 生成失败")
        return False, "❌ 生成Boss失败，请稍后重试。"
    boss_name = str(instance.get("boss_name") or "")
    if created:
        return True, f"✅ 已生成世界Boss：{boss_name}"
    if profile_id is None:
        return True, f"已有活跃世界 Boss {boss_name}。"
    requested = _requested_profile_name(service, profile_id)
    return True, f"已有活跃世界 Boss {boss_name}，未生成 {requested}。"


@dataclass(frozen=True)
class ChallengeResult:
    """Result of one atomic world-boss challenge attempt.

    Attributes:
        ok: Whether the attempt was settled (False for a rejection message).
        message: User-facing Chinese message.
        instance: Instance row after the attempt (None for hard rejections).
        challenge: Persisted challenge row (None for hard rejections).
        damage_dealt: Real damage of this attempt (hp_before - hp_after).
        is_last_hit: Whether this attempt landed the unique killing blow.
        phase: Instance phase after the attempt.
        phase_advanced: Phases the instance advanced through, in order.
        defeated: Whether the boss was defeated by this attempt.
    """

    ok: bool
    message: str
    instance: dict | None = None
    challenge: dict | None = None
    damage_dealt: int = 0
    is_last_hit: bool = False
    phase: int = 1
    phase_advanced: tuple[int, ...] = ()
    defeated: bool = False


class WorldBossService:
    """Own the fixed world-boss lifecycle and the atomic challenge transition.

    Args:
        db: DataBase instance (transaction seam).
        catalog: Validated EnemyCatalog holding the four world-boss profiles;
            None disables the whole domain (prd R1).
        health_service: HealthService (settle / CAS seam).
        busy_state: BusyState guard (assert_idle); None skips the busy gate.
        combat_manager: CombatManager (or a CombatEngine) exposing
            build_fighter_from_player / resolve_combat.
        config_manager: Optional config source read for
            ``pve.difficulty_multiplier`` (frozen at spawn) and the shared
            ``combat.base_crit_rate`` crit fallback.
        clock: Injectable business clock (unix seconds).
        rng: Injectable RNG used for profile selection (tests pin a seed).
        max_conflict_retries: Bounded recompute attempts on CAS conflict.
    """

    def __init__(
        self,
        db: Any,
        catalog: EnemyCatalog | None,
        health_service: Any,
        busy_state: Any,
        combat_manager: Any,
        config_manager: Any = None,
        *,
        clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
        max_conflict_retries: int = DEFAULT_MAX_CONFLICT_RETRIES,
    ) -> None:
        self.db = db
        self.catalog = catalog
        self.health_service = health_service
        self.busy_state = busy_state
        self.combat_engine = getattr(combat_manager, "engine", combat_manager)
        self.config_manager = config_manager
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self.max_conflict_retries = max(0, int(max_conflict_retries))

    # ------------------------------------------------------------------
    # repository seams
    # ------------------------------------------------------------------

    @property
    def instances(self) -> WorldBossRepository:
        """Repository over the world-boss instance/attempt/ledger tables."""
        return WorldBossRepository(self.db.conn)

    @property
    def outbox(self) -> OutboxRepository:
        """Repository over the business-event outbox tables."""
        return OutboxRepository(self.db.conn)

    @property
    def enabled(self) -> bool:
        """Whether the domain has a loaded catalog with at least one profile."""
        return self.catalog is not None and bool(self.catalog.world_bosses)

    async def get_active(self, *, now: int | None = None) -> dict | None:
        """Return the current active instance after settling expiry (query only).

        The query shares ``_consume_expired_active`` with ``ensure_spawn`` so an
        expired row read by the handler is dissipated in the same short
        transaction instead of lingering as "active". It never creates an
        instance (E2 design §4).

        Args:
            now: Business timestamp override; defaults to the service clock.

        Returns:
            The surviving active instance row, or None when the domain is
            disabled / no instance is active.
        """
        if not self.enabled:
            return None
        stamp = int(self.clock()) if now is None else int(now)
        async with self.db.transaction():
            return await self._consume_expired_active(stamp)

    def _profiles(self) -> tuple[WorldBossProfile, ...]:
        """Return the catalog world-boss profiles (empty when disabled)."""
        return tuple(self.catalog.world_bosses) if self.catalog else ()

    # ------------------------------------------------------------------
    # small helpers
    # ------------------------------------------------------------------

    def _snapshot(self, instance: dict) -> dict:
        """Parse the frozen birth snapshot of an instance row."""
        raw = instance.get("birth_snapshot")
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _snapshot_int(self, snapshot: dict, key: str, default: int) -> int:
        """Read a positive int from a snapshot with a contract default."""
        try:
            value = int(snapshot.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _snapshot_float(self, snapshot: dict, key: str, default: float) -> float:
        """Read a float from a snapshot with a contract default."""
        try:
            return float(snapshot.get(key, default))
        except (TypeError, ValueError):
            return default

    def _difficulty_multiplier(self) -> float:
        """Read pve.difficulty_multiplier once at spawn time (frozen per instance)."""
        config = getattr(self.config_manager, "game_config", None) or {}
        if not isinstance(config, dict):
            return 1.0
        pve = config.get("pve") or {}
        if not isinstance(pve, dict):
            return 1.0
        try:
            return float(pve.get("difficulty_multiplier", 1.0))
        except (TypeError, ValueError):
            return 1.0

    def _defeat_hp_floor(self, player: Player) -> int:
        """Return the single-source defeat floor (child E1), falling back to 1.

        Child E1 owns the floor formula (HealthService.defeat_hp_floor). This
        child must not introduce a second constant, so it capability-detects the
        API and uses 1 until E1 lands; after E1 the same call picks the real
        floor up automatically.
        """
        provider = getattr(self.health_service, "defeat_hp_floor", None)
        if callable(provider):
            try:
                return max(1, int(provider(player)))
            except (TypeError, ValueError):
                logger.warning("世界 Boss 气血地板计算失败，回退到 1")
        return 1

    @staticmethod
    def _challenge_seed(challenge_id: str) -> int:
        """Derive a stable RNG seed from the idempotency key (prd R4)."""
        digest = hashlib.sha256(challenge_id.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _roll_combat(self, player_fighter, boss_fighter, seed: int):
        """Run the engine with a pinned RNG stream (no await: atomic restore)."""
        saved = random.getstate()
        try:
            random.seed(seed)
            return self.combat_engine.resolve_combat(
                player_fighter, boss_fighter, combat_type="pve"
            )
        finally:
            random.setstate(saved)

    async def _append_event(
        self,
        *,
        business_key: str,
        event_type: str,
        instance_id: str,
        occurred_at: int,
        payload: dict,
    ) -> None:
        """Append one unique business event inside the caller's unit of work."""
        await self.outbox.append_event(
            event_id=f"evt:{business_key}",
            business_key=business_key,
            event_type=event_type,
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=instance_id,
            occurred_at=int(occurred_at),
            payload=payload,
        )

    # ------------------------------------------------------------------
    # spawn / lifecycle (prd R1, R2)
    # ------------------------------------------------------------------

    @staticmethod
    def _eligible_at(latest_terminal: dict | None) -> int:
        """Respawn eligibility epoch from the newest terminal instance (prd R1).

        next_spawn_at is the single authority; when it is somehow unset we fall
        back to terminated_at so a corrupt legacy row still orders correctly.
        """
        if latest_terminal is None:
            return 0
        try:
            next_at = int(latest_terminal.get("next_spawn_at") or 0)
        except (TypeError, ValueError):
            next_at = 0
        if next_at > 0:
            return next_at
        try:
            return int(latest_terminal.get("terminated_at") or 0)
        except (TypeError, ValueError):
            return 0

    async def _consume_expired_active(self, now: int) -> dict | None:
        """Dissipate expired active instances, then return the live active one.

        prd R1: this runs inside the caller's transaction, before the active
        read, so an expired row can never block a new spawn and the conversion
        itself is idempotent (CAS on state + version).
        """
        for row in await self.instances.list_instances(
            states=(INSTANCE_STATE_ACTIVE,), limit=50
        ):
            if int(row.get("expires_at") or 0) > now:
                return row
            await self._dissipate(row, now=now)
        return None

    async def _dissipate(self, row: dict, *, now: int) -> bool:
        """Move an expired active instance to dissipated with its respawn time.

        Returns:
            True when the transition was applied by this call, False when the
            row was already terminal or lost the CAS race (idempotent replay).
        """
        instance_id = row["instance_id"]
        ended_at = int(row.get("expires_at") or now)
        snapshot = self._snapshot(row)
        respawn_h = self._snapshot_int(
            snapshot, "respawn_after_dissipate_h", DEFAULT_RESPAWN_DISSIPATE_H
        )
        applied = await self.instances.cas_update_instance(
            instance_id,
            expected={
                "cas_version": int(row["cas_version"]),
                "state": INSTANCE_STATE_ACTIVE,
            },
            state=INSTANCE_STATE_DISSIPATED,
            terminated_at=ended_at,
            next_spawn_at=ended_at + respawn_h * 3600,
        )
        if not applied:
            return False
        logger.info(
            "世界 Boss 到期消散：%s（再生时刻 %s）",
            instance_id,
            ended_at + respawn_h * 3600,
        )
        await self._append_event(
            business_key=dissipated_business_key(instance_id),
            event_type=EVENT_DISSIPATED,
            instance_id=instance_id,
            occurred_at=now,
            payload={
                "copy_key": "dissipate_text",
                "boss_name": row.get("boss_name", ""),
                "profile_id": row.get("profile_id", ""),
            },
        )
        return True

    def _select_profile(
        self, profile_id: str | None, eligible_at: int, now: int
    ) -> tuple[WorldBossProfile, str, int]:
        """Select the profile to spawn (prd R1 regular / GM-forced branches).

        Args:
            profile_id: Explicit profile (GM force) or None for the regular path.
            eligible_at: Respawn eligibility epoch from the newest terminal row.
            now: Business timestamp.

        Returns:
            (profile, selection_source, seed).

        Raises:
            WorldBossSpawnRejected: Unknown profile id, or the regular path is
                not yet eligible.
        """
        profiles = self._profiles()
        if profile_id is not None:
            for profile in profiles:
                if profile.id == profile_id:
                    return profile, "forced", 0
            raise WorldBossSpawnRejected(f"❌ 未知的世界 Boss 档案：{profile_id}")
        if now < eligible_at:
            raise WorldBossSpawnRejected("❌ 世界 Boss 尚未到再生时间。")
        seed = self.rng.randrange(1, 2**31)
        picker = random.Random(seed)
        return profiles[picker.randrange(len(profiles))], "seed", seed

    def _birth_snapshot(
        self,
        profile: WorldBossProfile,
        *,
        spawn_epoch: int,
        selection_source: str,
        seed: int,
    ) -> dict:
        """Freeze everything the instance needs, including narrative facts (R7)."""
        return {
            "profile_id": profile.id,
            "profile_version": int(profile.profile_version),
            "boss_name": profile.name,
            "segment": profile.segment,
            "level_index": int(profile.level_index),
            "max_hp": int(profile.hp),
            "damage": int(profile.damage),
            "agility": int(profile.agility),
            "speed": int(profile.speed),
            "armor_value": int(profile.armor_value),
            "crit_rate": int(profile.crit_rate),
            "skill_key": profile.skill_key,
            "trigger_skills": [dict(s) for s in profile.trigger_skills],
            "ultimates": [dict(u) for u in profile.ultimates],
            "phase_thresholds": [float(p) for p in profile.phase_thresholds],
            "phase2_damage_multiplier": float(profile.phase2_damage_multiplier),
            "phase3_damage_multiplier": float(profile.phase3_damage_multiplier),
            "phase3_armor_multiplier": float(profile.phase3_armor_multiplier),
            "lifetime_h": int(profile.lifetime_h),
            "daily_attempts": int(profile.daily_attempts),
            "respawn_after_kill_h": int(profile.respawn_after_kill_h),
            "respawn_after_dissipate_h": int(profile.respawn_after_dissipate_h),
            # 难度倍率在出生时固化：之后热更新 config 不影响进行中的实例（prd R4）。
            "difficulty_multiplier": self._difficulty_multiplier(),
            "seed": int(seed),
            "selected_profile_id": profile.id,
            "selection_source": selection_source,
            "scheduled_epoch": int(spawn_epoch),
            "spawn_text": profile.spawn_text,
            "phase2_text": profile.phase2_text,
            "phase3_text": profile.phase3_text,
            "kill_text": profile.kill_text,
            "dissipate_text": profile.dissipate_text,
            "narrative_approved": bool(profile.narrative_approved),
            "narrative_status": profile.narrative_status,
            "status": profile.status,
        }

    async def _create_instance(
        self,
        profile: WorldBossProfile,
        *,
        spawn_epoch: int,
        now: int,
        selection_source: str,
        seed: int,
    ) -> tuple[dict, bool, str]:
        """Insert the fixed instance (idempotent) and append its spawn event."""
        instance_id = f"wb_{profile.id}_{spawn_epoch}"
        snapshot = self._birth_snapshot(
            profile,
            spawn_epoch=spawn_epoch,
            selection_source=selection_source,
            seed=seed,
        )
        lifetime_h = int(profile.lifetime_h or DEFAULT_LIFETIME_H)
        row, created = await self.instances.insert_instance(
            instance_id=instance_id,
            profile_id=profile.id,
            profile_version=int(profile.profile_version),
            max_hp=int(profile.hp),
            now=now,
            expires_at=now + lifetime_h * 3600,
            boss_name=profile.name,
            boss_level=int(profile.level_index),
            atk=int(profile.damage),
            defense=0,
            agility=int(profile.agility),
            speed=int(profile.speed),
            armor_value=int(profile.armor_value),
            birth_snapshot=snapshot,
        )
        if not created:
            # Concurrent insert lost the primary-key race: the winner's row must
            # still be the single active instance (prd R1).
            fresh = await self.instances.get_instance(instance_id)
            if fresh is None or fresh.get("state") != INSTANCE_STATE_ACTIVE:
                raise WorldBossSpawnRejected("❌ 世界 Boss 生成冲突，请稍后重试。")
            logger.info("世界 Boss 实例已存在，复用：%s", instance_id)
            return fresh, False, str(fresh["profile_id"])
        log_birth = logger.warning if selection_source == "forced" else logger.info
        log_birth(
            "世界 Boss 出生：%s（segment=%s source=%s epoch=%s）",
            instance_id,
            profile.segment,
            selection_source,
            spawn_epoch,
        )
        await self._append_event(
            business_key=spawn_business_key(instance_id),
            event_type=EVENT_SPAWN,
            instance_id=instance_id,
            occurred_at=now,
            payload={
                "copy_key": "spawn_text",
                "boss_name": profile.name,
                "profile_id": profile.id,
                "segment": profile.segment,
            },
        )
        return row, True, profile.id

    async def ensure_spawn(
        self, profile_id: str | None = None
    ) -> tuple[dict, bool, str]:
        """Ensure a single active instance exists; return the fixed spawn facts.

        prd R1 contract: the active read + insert share one transaction, expired
        active rows are dissipated first, at most one active instance survives,
        and only an actually created instance appends a spawn event.

        Args:
            profile_id: Explicit profile forced by a GM command; None keeps the
                regular random path (and requires respawn eligibility).

        Returns:
            (instance_row, created, resolved_profile_id). When an instance is
            already active it is returned with created=False and its real
            profile id, even if a different profile was requested.

        Raises:
            WorldBossSpawnRejected: Domain disabled, unknown profile id, not yet
                eligible for the regular path, or an inconsistent insert race.
        """
        if not self.enabled:
            raise WorldBossSpawnRejected("❌ 世界 Boss 玩法未启用。")
        now = int(self.clock())
        rejection: WorldBossSpawnRejected | None = None
        result: tuple[dict, bool, str] | None = None
        async with self.db.transaction():
            active = await self._consume_expired_active(now)
            if active is not None:
                if profile_id is not None and profile_id != active.get("profile_id"):
                    logger.warning(
                        "已有活跃世界 Boss %s，未生成 %s",
                        active.get("boss_name", ""),
                        profile_id,
                    )
                return active, False, str(active["profile_id"])
            latest = await self.instances.get_latest_terminal_instance()
            eligible_at = self._eligible_at(latest)
            try:
                profile, source, seed = self._select_profile(
                    profile_id, eligible_at, now
                )
            except WorldBossSpawnRejected as exc:
                # 已在同一事务内完成的到期消散必须提交；拒绝理由留到事务外抛出，
                # 否则回滚会把消散转换丢掉（下一次轮询又会重复判定为 active）。
                rejection = exc
            else:
                # The spawn epoch is the eligibility instant being consumed; a
                # first ever spawn uses now so the id stays deterministic.
                spawn_epoch = eligible_at if latest is not None else now
                result = await self._create_instance(
                    profile,
                    spawn_epoch=spawn_epoch,
                    now=now,
                    selection_source=source,
                    seed=seed,
                )
        if rejection is not None:
            raise rejection
        assert result is not None
        return result

    # ------------------------------------------------------------------
    # challenge (prd R4, R5, R6)
    # ------------------------------------------------------------------

    async def _prepare_challenge(
        self, user_id: str, instance_id: str | None, now: int
    ) -> ChallengeResult | dict:
        """Settle health and capture the pre-fight snapshot in one short txn.

        Args:
            user_id: Challenger.
            instance_id: Explicit instance, or None for the current active one.
            now: Business timestamp.

        Returns:
            Snapshot dict for the combat phase, or a rejection ChallengeResult.
        """
        async with self.db.transaction():
            player = await self.db.get_player_by_id(user_id)
            if player is None:
                return ChallengeResult(ok=False, message="❌ 玩家不存在。")
            # 战前结算放在同一个短事务里（bd -dfb：悬空隐式事务竞态）。
            await self.health_service.settle(user_id, now=now)
            player = await self.db.get_player_by_id(user_id)
            if player is None:
                return ChallengeResult(ok=False, message="❌ 玩家不存在。")

            instance = None
            if instance_id is not None:
                instance = await self.instances.get_instance(instance_id)
            else:
                active_rows = await self.instances.list_instances(
                    states=(INSTANCE_STATE_ACTIVE,), limit=1
                )
                instance = active_rows[0] if active_rows else None
            if instance is None:
                return ChallengeResult(
                    ok=False, message="❌ 当前没有可挑战的世界 Boss。"
                )
            if instance.get("state") != INSTANCE_STATE_ACTIVE:
                return ChallengeResult(
                    ok=False, message="❌ 该世界 Boss 已不在挑战期。", instance=instance
                )
            if int(instance.get("expires_at") or 0) <= now:
                return ChallengeResult(
                    ok=False, message="❌ 该世界 Boss 已消散。", instance=instance
                )

            date_key = shanghai_date_key(now)
            snapshot = self._snapshot(instance)
            daily_limit = self._snapshot_int(
                snapshot, "daily_attempts", DEFAULT_DAILY_ATTEMPTS
            )
            counter = await self.instances.get_daily_attempts(
                date_key=date_key, user_id=user_id
            )
            if (
                counter is not None
                and int(counter.get("attempts_used") or 0) >= daily_limit
            ):
                return ChallengeResult(
                    ok=False,
                    message=f"❌ 今日世界 Boss 挑战次数已用完（每日 {daily_limit} 次）。",
                    instance=instance,
                )
            return {
                "instance": instance,
                "player": player,
                "date_key": date_key,
                "daily_limit": daily_limit,
                "player_current_hp": int(player.current_hp),
                "health_recovered_at": int(
                    getattr(player, "health_recovered_at", 0) or 0
                ),
            }

    def _base_crit_rate(self) -> float | int:
        """Read the shared monster crit fallback from ``game_config``.

        E1 owns the contract (``combat.base_crit_rate``): a positive per-enemy
        percentage still overrides it in :func:`build_enemy_fighter`; missing
        key or ``None`` falls back to 0.15; an explicit ``0`` disables crit.

        Returns:
            Configured fallback rate, or 0.15 when unavailable.
        """
        config = getattr(self.config_manager, "game_config", None)
        if isinstance(config, dict):
            combat = config.get("combat", {})
            if isinstance(combat, dict):
                configured = combat.get("base_crit_rate")
                if configured is not None:
                    return configured
        return 0.15

    def _build_instance_fighter(self, instance: dict) -> Any:
        """Build the boss FighterState from frozen facts and the persisted phase."""
        snapshot = self._snapshot(instance)
        phase = max(1, min(3, int(instance.get("phase") or 1)))
        difficulty = self._snapshot_float(snapshot, "difficulty_multiplier", 1.0)
        phase_mult = 1.0
        if phase == 2:
            phase_mult = self._snapshot_float(
                snapshot, "phase2_damage_multiplier", DEFAULT_PHASE2_DAMAGE_MULT
            )
        elif phase >= 3:
            phase_mult = self._snapshot_float(
                snapshot, "phase3_damage_multiplier", DEFAULT_PHASE3_DAMAGE_MULT
            )
        armor_mult = (
            self._snapshot_float(
                snapshot, "phase3_armor_multiplier", DEFAULT_PHASE3_ARMOR_MULT
            )
            if phase >= 3
            else 1.0
        )
        base_damage = int(instance.get("atk") or 0)
        damage = max(1, int(round(base_damage * difficulty * phase_mult)))
        armor = max(0, int(round(int(instance.get("armor_value") or 0) * armor_mult)))
        enemy = Enemy(
            user_id=f"world_boss:{instance['instance_id']}",
            name=str(instance.get("boss_name") or ""),
            hp=int(instance.get("current_hp") or 0),
            max_hp=int(instance.get("max_hp") or 0),
            damage=damage,
            agility=int(instance.get("agility") or 0),
            speed=int(instance.get("speed") or 0),
            armor_value=armor,
            exp=0,
            crit_rate=int(snapshot.get("crit_rate") or 0),
            profile_id=str(instance.get("profile_id") or ""),
            level_index=int(instance.get("boss_level") or 0),
            trigger_skills=[dict(s) for s in snapshot.get("trigger_skills") or []],
            ultimates=[dict(u) for u in snapshot.get("ultimates") or []],
            atk=damage,
            defense=armor,
        )
        return build_enemy_fighter(enemy, base_crit_rate=self._base_crit_rate())

    async def _run_challenge_combat(self, snapshot: dict, seed: int) -> dict:
        """Run the deterministic fight outside any transaction (prd R4)."""
        instance = snapshot["instance"]
        player = snapshot["player"]
        player_fighter = await self.combat_engine.build_fighter_from_player(player)
        boss_fighter = self._build_instance_fighter(instance)
        result = self._roll_combat(player_fighter, boss_fighter, seed)
        hp_before = int(instance.get("current_hp") or 0)
        hp_after = max(0, int(result.fighter2_final_hp))
        return {
            "damage_dealt": max(0, hp_before - hp_after),
            "boss_hp_before": hp_before,
            "boss_hp_after": hp_after,
            "player_hp_after": max(
                int(result.fighter1_final_hp), self._defeat_hp_floor(player)
            ),
        }

    @staticmethod
    def _next_phase(instance: dict, snapshot: dict, hp_after: int) -> int:
        """Advance the phase from the persisted HP ratio (never regress, R5)."""
        thresholds = snapshot.get("phase_thresholds") or list(DEFAULT_PHASE_THRESHOLDS)
        try:
            threshold2 = float(thresholds[0])
            threshold3 = float(thresholds[1])
        except (TypeError, ValueError, IndexError):
            threshold2, threshold3 = DEFAULT_PHASE_THRESHOLDS
        max_hp = max(1, int(instance.get("max_hp") or 0))
        ratio = hp_after / max_hp
        target = 1
        if ratio <= threshold3:
            target = 3
        elif ratio <= threshold2:
            target = 2
        return max(int(instance.get("phase") or 1), target)

    async def _commit_challenge(
        self,
        snapshot: dict,
        combat: dict,
        *,
        challenge_id: str,
    ) -> ChallengeResult | None:
        """Apply the settled attempt in one short transaction (prd R4 order).

        Returns:
            The settled result, a rejection, or None when a CAS lost the race
            (the caller recomputes the same deterministic fight and retries).
        """
        now = int(self.clock())
        instance_snapshot = snapshot["instance"]
        player: Player = snapshot["player"]
        instance_id = instance_snapshot["instance_id"]
        damage = int(combat["damage_dealt"])
        hp_before = int(combat["boss_hp_before"])
        hp_after = int(combat["boss_hp_after"])
        is_last_hit = hp_after == 0

        async with self.db.transaction() as txn:
            instance = await self.instances.get_instance(instance_id)
            if instance is None or instance.get("state") != INSTANCE_STATE_ACTIVE:
                txn.abort()
                return ChallengeResult(
                    ok=False, message="❌ 该世界 Boss 已不在挑战期。"
                )
            if int(instance.get("expires_at") or 0) <= now:
                txn.abort()
                return ChallengeResult(ok=False, message="❌ 该世界 Boss 已消散。")
            # Any movement since the combat snapshot invalidates the settled
            # result: recompute rather than applying old damage to new HP.
            if int(instance["cas_version"]) != int(instance_snapshot["cas_version"]):
                txn.abort()
                return None
            if int(instance.get("current_hp") or 0) != int(
                instance_snapshot.get("current_hp") or 0
            ):
                txn.abort()
                return None

            frozen = self._snapshot(instance)
            phase_before = int(instance.get("phase") or 1)
            phase_after = self._next_phase(instance, frozen, hp_after)
            values: dict[str, Any] = {"current_hp": hp_after, "phase": phase_after}
            if is_last_hit:
                respawn_h = self._snapshot_int(
                    frozen, "respawn_after_kill_h", DEFAULT_RESPAWN_KILL_H
                )
                values["state"] = INSTANCE_STATE_DEFEATED
                values["terminated_at"] = now
                values["next_spawn_at"] = now + respawn_h * 3600

            # 1) instance CAS (phase + HP + optional terminal transition)
            applied = await self.instances.cas_update_instance(
                instance_id,
                expected={
                    "cas_version": int(instance["cas_version"]),
                    "state": INSTANCE_STATE_ACTIVE,
                    "current_hp": int(instance.get("current_hp") or 0),
                },
                **values,
            )
            if not applied:
                txn.abort()
                return None

            # 2) consume the daily attempt (refuses without consuming at the cap)
            counter = await self.instances.increment_daily_attempts(
                date_key=snapshot["date_key"],
                user_id=player.user_id,
                limit=int(snapshot["daily_limit"]),
            )
            if counter is None:
                txn.abort()
                return ChallengeResult(
                    ok=False,
                    message=(
                        "❌ 今日世界 Boss 挑战次数已用完"
                        f"（每日 {snapshot['daily_limit']} 次）。"
                    ),
                    instance=instance,
                )

            # 3) player health CAS (pre-image captured by the settle txn)
            fresh_player = await self.db.get_player_by_id(player.user_id)
            if fresh_player is None:
                txn.abort()
                return ChallengeResult(ok=False, message="❌ 玩家不存在。")
            if int(fresh_player.current_hp) != int(snapshot["player_current_hp"]):
                txn.abort()
                return None
            if int(getattr(fresh_player, "health_recovered_at", 0) or 0) != int(
                snapshot["health_recovered_at"]
            ):
                txn.abort()
                return None
            health_applied = await self.instances.cas_update_player_health(
                user_id=player.user_id,
                expected_current_hp=int(fresh_player.current_hp),
                expected_health_recovered_at=int(
                    getattr(fresh_player, "health_recovered_at", 0) or 0
                ),
                new_current_hp=int(combat["player_hp_after"]),
            )
            if not health_applied:
                txn.abort()
                return None

            # 4) challenge fact / ledger / contribution / events
            outcome = (
                CHALLENGE_OUTCOME_DEFEATED if is_last_hit else CHALLENGE_OUTCOME_ONGOING
            )
            challenge_row, challenge_created = await self.instances.record_challenge(
                challenge_id=challenge_id,
                instance_id=instance_id,
                user_id=player.user_id,
                date_key=snapshot["date_key"],
                outcome=outcome,
                damage_dealt=damage,
                hp_before=hp_before,
                hp_after=hp_after,
                player_hp_before=int(snapshot["player_current_hp"]),
                player_hp_after=int(combat["player_hp_after"]),
                instance_cas_version=int(instance["cas_version"]),
                now=now,
                fled=False,
                is_last_hit=is_last_hit,
                phase_changed=phase_after - phase_before,
            )
            if not challenge_created:
                # Lost the idempotency race: settle nothing twice.
                txn.abort()
                return ChallengeResult(
                    ok=True,
                    message="✅ 本次世界 Boss 挑战已结算，无需重复提交。",
                    instance=instance,
                    challenge=challenge_row,
                    damage_dealt=int(challenge_row["damage_dealt"]),
                    is_last_hit=bool(challenge_row["is_last_hit"]),
                    phase=phase_before,
                )
            await self.instances.record_ledger(
                instance_id=instance_id,
                challenge_id=challenge_id,
                user_id=player.user_id,
                profile_version=int(instance.get("profile_version") or 0),
                damage_dealt=damage,
                now=now,
            )
            await self.instances.accumulate_contribution(
                instance_id=instance_id,
                user_id=player.user_id,
                profile_version=int(instance.get("profile_version") or 0),
                damage_dealt=damage,
                now=now,
                is_last_hit=is_last_hit,
            )

            phase_advanced = tuple(range(phase_before + 1, phase_after + 1))
            for phase in phase_advanced:
                await self._append_event(
                    business_key=stage_business_key(instance_id, phase),
                    event_type=EVENT_STAGE,
                    instance_id=instance_id,
                    occurred_at=now,
                    payload={
                        "copy_key": COPY_KEY_BY_PHASE.get(phase, "phase3_text"),
                        "phase": phase,
                        "boss_name": instance.get("boss_name", ""),
                        "profile_id": instance.get("profile_id", ""),
                    },
                )
            if is_last_hit:
                await self._append_event(
                    business_key=defeated_business_key(instance_id),
                    event_type=EVENT_DEFEATED,
                    instance_id=instance_id,
                    occurred_at=now,
                    payload={
                        "copy_key": "kill_text",
                        "boss_name": instance.get("boss_name", ""),
                        "profile_id": instance.get("profile_id", ""),
                    },
                )

            fresh_instance = await self.instances.get_instance(instance_id) or instance
            return ChallengeResult(
                ok=True,
                message=self._challenge_message(
                    boss_name=str(instance.get("boss_name") or ""),
                    damage=damage,
                    hp_after=hp_after,
                    max_hp=int(instance.get("max_hp") or 0),
                    phase_advanced=phase_advanced,
                    is_last_hit=is_last_hit,
                ),
                instance=fresh_instance,
                challenge=challenge_row,
                damage_dealt=damage,
                is_last_hit=is_last_hit,
                phase=int(fresh_instance.get("phase") or phase_after),
                phase_advanced=phase_advanced,
                defeated=is_last_hit,
            )

    @staticmethod
    def _challenge_message(
        *,
        boss_name: str,
        damage: int,
        hp_after: int,
        max_hp: int,
        phase_advanced: tuple[int, ...],
        is_last_hit: bool,
    ) -> str:
        """Compose the user-facing challenge report (services own messages)."""
        parts = [
            f"⚔️ 你对「{boss_name}」造成 {damage} 点伤害（剩余 {hp_after}/{max_hp}）。"
        ]
        if phase_advanced:
            parts.append(f"「{boss_name}」进入第 {max(phase_advanced)} 阶段！")
        if is_last_hit:
            parts.append(f"🎯 你给予了「{boss_name}」最后一击！")
        return "".join(parts)

    async def challenge(
        self,
        *,
        player: Player,
        challenge_id: str,
        instance_id: str | None = None,
        rng_seed: int | None = None,
    ) -> ChallengeResult:
        """Run one atomic challenge attempt (prd R4).

        Args:
            player: Challenger (only user_id is trusted; state is re-read).
            challenge_id: Idempotency key of this attempt; replays settle once.
            instance_id: Explicit instance, or None for the current active one.
            rng_seed: Optional pin; defaults to a digest of challenge_id so a
                conflict retry replays exactly the same fight.

        Returns:
            ChallengeResult with the settled facts or a rejection message.
        """
        if not challenge_id:
            raise ValueError("challenge_id is required")
        if not self.enabled:
            return ChallengeResult(ok=False, message="❌ 世界 Boss 玩法未启用。")

        replay = await self.instances.get_challenge(challenge_id)
        if replay is not None:
            instance = await self.instances.get_instance(replay["instance_id"])
            return ChallengeResult(
                ok=True,
                message="✅ 本次世界 Boss 挑战已结算，无需重复提交。",
                instance=instance,
                challenge=replay,
                damage_dealt=int(replay["damage_dealt"]),
                is_last_hit=bool(replay["is_last_hit"]),
                phase=int(instance.get("phase") or 1) if instance else 1,
                defeated=bool(replay["is_last_hit"]),
            )

        if self.busy_state is not None:
            busy_message = await self.busy_state.assert_idle(
                player.user_id, template=BUSY_TEMPLATE
            )
            if busy_message:
                return ChallengeResult(ok=False, message=busy_message)

        seed = (
            int(rng_seed)
            if rng_seed is not None
            else self._challenge_seed(challenge_id)
        )
        for _ in range(self.max_conflict_retries + 1):
            now = int(self.clock())
            snapshot = await self._prepare_challenge(player.user_id, instance_id, now)
            if isinstance(snapshot, ChallengeResult):
                return snapshot
            combat = await self._run_challenge_combat(snapshot, seed)
            result = await self._commit_challenge(
                snapshot, combat, challenge_id=challenge_id
            )
            if result is not None:
                return result
        logger.warning("世界 Boss 挑战连续冲突，放弃本次结算：%s", challenge_id)
        return ChallengeResult(
            ok=False, message="❌ 世界 Boss 挑战结算冲突，请稍后重试。"
        )
