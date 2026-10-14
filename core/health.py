"""Player health domain — single owner of current_hp / max_hp / lazy recovery.

Trellis task 10-10-pve-player-health-foundation (child A), design D2/D3.

The health model has three layers with disjoint ownership:

- players.base_hp     permanent foundation. Only the permanent-foundation
  consumers change it — breakthrough (level_up), permanent pills (含回生丹
  减半), GM 设置气血 — either directly on the field or via
  HealthService.add_base_hp. Combat/recovery/普通药品 NEVER touch it.
- players.current_hp  live combat health, invariant 0 <= current_hp <=
  max_hp. Combat write-backs, pills that 回复气血, shop 气血 items and lazy
  recovery are the ONLY generic boundary changing it
  (apply_current_hp_change / set_current_hp / heal_to_full).
- max_hp              NEVER persisted. Computed at runtime as
  Player.get_total_attributes(equipped_items)["max_hp"] = base_hp +
  equipment/technique/heart-method bonuses (same aggregation combat uses —
  pill percent buffs stay display-side only, matching the pre-split combat
  ceiling built with pill_multipliers=None).

Lazy recovery (parent design 气血战后自然恢复): 1% of the dynamic max per
elapsed minute, settled lazily on any authoritative read — never a
per-player timer. Recovery is purely time-based: it does NOT consult
user_cd/players.state, so a player keeps healing through 闭关/修炼/历练
pending windows as well (2026-10-12 用户拍板：取消恢复的忙碌判定，战斗结束
扣完血立刻开始回血；口径见 design_docs/content-design/pve-enemy-design.md
轴三 2 与 §Q4，Trellis task 10-10-pve-adventure-settlement R6). The old gate
consumed busy time (anchor jump without healing); it is gone, so no
retro-active catch-up special case is needed — elapsed time simply heals.
players.health_recovered_at is deliberately NOT registered in
core/time_skip_registry.TIME_SKIP_ENTRIES
(GM 时间快进 must not fast-forward recovery —
tests/test_player_health_foundation.py pins this boundary).

Restart-safe and idempotent: anchor == 0 only adopts the clock (no epoch
retro-heal); repeated reads in the same minute are no-ops; helpers gate
their commit on conn._txn_depth so a settle joining an outer transaction
spec (database-guidelines D2) rolls back atomically with it.
"""

import time

try:
    from ..data import DataBase
    from ..models import Player
except ImportError:  # standalone (tests) fallback, same idiom as busy_state.py
    DataBase = object
    Player = object

# 每分钟恢复动态 max_hp 的百分比（父设计 PVE: 气血战后自然恢复 1%/min）。
RECOVERY_RATE_PER_MINUTE = 0.01
SECONDS_PER_MINUTE = 60


class HealthService:
    """Single entry point for player health reads/writes (design D3).

    No reward, no platform message, no logging side effects here — callers
    keep their own narrative; the domain only moves the numbers and
    persists them (AC5: PVE/Boss can reuse it without dragging rewards
    along).

    Args:
        db: plugin DataBase instance.
        config_manager: ConfigManager (items_data/weapons_data/
            heart_methods_data for the max_hp equipment aggregation).
        equipment_manager: core EquipmentManager used to resolve equipped
            item configs; None degrades max_hp to base_hp (fresh/legacy
            callers without equipment wiring).
        clock: injectable business clock (unix seconds); tests pass a fake
            to drive elapsed-time recovery deterministically.
    """

    def __init__(self, db, config_manager, equipment_manager=None, clock=time.time):
        self._db = db
        self._config = config_manager
        self._equipment = equipment_manager
        self._clock = clock

    # ------------------------------------------------------------------
    # max_hp aggregation (runtime only, never persisted)
    # ------------------------------------------------------------------

    def compute_max_hp(self, player: Player) -> int:
        """Dynamic ceiling: base_hp + equipment/technique/heart-method bonuses.

        Floor at 1 so a zero/negative aggregation (legacy mock players) can
        never make the current-hp clamp collapse everything to 0.
        """
        equipped = []
        if self._equipment is not None and self._config is not None:
            # Combat/panel/health all share the equipment chain's builder
            # (weapon, armor, main heart method, technique list), so the
            # recovery ceiling equals the combat ceiling — a player can never
            # exceed what combat knows.
            equipped = self._equipment.get_equipped_items(
                player,
                self._config.items_data,
                self._config.weapons_data,
                self._config.heart_methods_data,
            )
        attrs = player.get_total_attributes(equipped, pill_multipliers=None)
        return max(1, int(attrs["max_hp"]))

    # ------------------------------------------------------------------
    # lazy recovery settlement
    # ------------------------------------------------------------------

    async def settle(self, user_id: str, now: int | None = None) -> int:
        """Advance lazy recovery for user_id, persist it, return settled current_hp.

        Recovery is time-based only — 忙碌状态（user_cd）不参与判定，
        闭关/修炼/历练 pending 期间同样按分钟回血（2026-10-12 用户拍板，
        见模块头与 §Q4）。Called by every normal health read and by the
        busy-state write path (inside the caller outer db.transaction() — the
        same-transaction join is what makes settle + anchor-advance and the
        new status atomic together, design D3). anchor == 0 adopts now without
        retroactive healing, so the migration checkpoint and legacy rows start
        clean.
        """
        now = int(now if now is not None else self._clock())
        conn = self._db.conn
        async with conn.execute(
            "SELECT base_hp, current_hp, health_recovered_at, level_index, "
            "cultivation_type, weapon, armor, main_technique, techniques "
            "FROM players WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return 0
        data = dict(row)
        anchor = int(data["health_recovered_at"] or 0)
        current = int(
            data["current_hp"] if data["current_hp"] is not None else data["base_hp"]
        )
        if anchor == 0:
            await self._write_anchor(user_id, current, now)
            return current

        max_hp = self._max_from_row(data)
        elapsed = max(0, now - anchor)
        minutes = elapsed // SECONDS_PER_MINUTE
        if minutes <= 0:
            return current
        # 1%/min of the DYNAMIC max (parent design); heal is floored per full
        # minute and the anchor advances by whole minutes only, so
        # sub-minute remainders carry into the next window (no double heal,
        # no lost seconds). Per-minute gain is floored at 1 so a fresh
        # 灵修 roll 90–99 without equipment (max_hp < 100) still recovers
        # instead of soft-locking at int(max * 1%) == 0.
        heal = max(1, int(max_hp * RECOVERY_RATE_PER_MINUTE)) * minutes
        new_current = min(max_hp, max(0, current + heal))
        new_anchor = anchor + minutes * SECONDS_PER_MINUTE
        await self._write_anchor(user_id, new_current, new_anchor)
        return new_current

    async def _write_anchor(self, user_id: str, current_hp: int, anchor: int) -> None:
        conn = self._db.conn
        await conn.execute(
            "UPDATE players SET current_hp = ?, health_recovered_at = ? "
            "WHERE user_id = ?",
            (int(current_hp), int(anchor), user_id),
        )
        # D2 ownership gate: commit only outside an active CM transaction.
        if getattr(conn, "_txn_depth", 0) == 0:
            await conn.commit()

    def _max_from_row(self, data: dict) -> int:
        """max_hp for a raw players row without loading the full Player.

        Only the hp-aggregation inputs are rebuilt; other fields do not
        feed the max_hp key (see Player.get_total_attributes).
        """
        player = Player(
            user_id="",
            base_hp=int(data["base_hp"]),
            level_index=int(data["level_index"]),
            cultivation_type=data["cultivation_type"] or "灵修",
            weapon=data.get("weapon") or "",
            armor=data.get("armor") or "",
            main_technique=data.get("main_technique") or "",
            techniques=data.get("techniques") or "[]",
        )
        return self.compute_max_hp(player)

    # ------------------------------------------------------------------
    # snapshot + boundaries (the only generic current-hp writers)
    # ------------------------------------------------------------------

    async def get_health_snapshot(self, player: Player, now: int | None = None) -> dict:
        """Settle lazy recovery, enforce the invariant, return the 3 layers.

        Syncs the in-memory player's current_hp so callers cannot act on a
        stale value after reading the snapshot. The recovery anchor is NOT
        synced: it is a domain-owned column excluded from update_player
        (data/data_manager.py), so the stale in-memory anchor is never
        persisted back.
        """
        current = await self.settle(player.user_id, now=now)
        max_hp = self.compute_max_hp(player)
        current = max(0, min(current, max_hp))
        if current != int(player.current_hp or 0):
            await self._persist_current(player.user_id, current)
        player.current_hp = current
        return {
            "base_hp": int(player.base_hp),
            "current_hp": current,
            "max_hp": max_hp,
        }

    async def _persist_current(self, user_id: str, current_hp: int) -> None:
        conn = self._db.conn
        await conn.execute(
            "UPDATE players SET current_hp = ? WHERE user_id = ?",
            (int(current_hp), user_id),
        )
        if getattr(conn, "_txn_depth", 0) == 0:
            await conn.commit()

    async def clamp_current_hp(self, player: Player) -> int:
        """Re-assert 0 <= current_hp <= max_hp after max_hp may have dropped.

        Used when equipment/technique bonuses shrink (卸下装备/换功法) so the
        persisted current can never exceed the new ceiling.
        """
        max_hp = self.compute_max_hp(player)
        current = max(0, min(int(player.current_hp or 0), max_hp))
        if current != int(player.current_hp or 0):
            await self._persist_current(player.user_id, current)
        player.current_hp = current
        return current

    async def apply_current_hp_change(
        self, player: Player, delta: int, minimum: int = 0
    ) -> int:
        """The generic current-hp boundary: settle, add delta, clamp, persist.

        minimum lets callers keep old floors (战后保底 1、商店气血药最低 1)
        without hand-writing the arithmetic; it never lifts a dead player
        above 0 unless the caller explicitly asks.
        """
        settled = await self.settle(player.user_id)
        player.current_hp = settled
        max_hp = self.compute_max_hp(player)
        current = max(minimum, min(max_hp, settled + int(delta)))
        await self._persist_current(player.user_id, current)
        player.current_hp = current
        return current

    async def set_current_hp(self, player: Player, value: int) -> int:
        """Absolute current-hp write (post-battle write-back), settled+clamped."""
        settled = await self.settle(player.user_id)
        player.current_hp = settled
        max_hp = self.compute_max_hp(player)
        current = max(0, min(max_hp, int(value)))
        await self._persist_current(player.user_id, current)
        player.current_hp = current
        return current

    async def heal_to_full(self, player: Player) -> int:
        """Full 气血丹 style effect: current = dynamic max."""
        return await self.set_current_hp(player, self.compute_max_hp(player))

    async def add_base_hp(self, player: Player, amount: int) -> int:
        """Explicit permanent base-HP growth (突破/永久丹/GM): base only.

        current_hp is deliberately untouched — growth raises the ceiling,
        it does not heal. Floored at 1 (same floor as the shop fallback and
        回生丹减半) so base_hp can never reach 0. Returns the new base_hp.
        """
        player.base_hp = max(1, int(player.base_hp) + int(amount))
        return player.base_hp
