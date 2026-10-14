# data/pve_repository.py
"""Transaction-joining repositories for the PVE persistence foundation (child P).

本模块只提供 **schema 写入契约 + 幂等 / CAS / claim 原子原语**，不实现任何领域
行为：不跑 CombatEngine、不计算逃跑与阶段、不渲染消息、不在数据库事务内等待
网络。领域状态机（历练结算流程、世界 Boss 生命周期、群广播投递）由 children
C/D/E 在 ``async with db.transaction():`` 内组合调用本模块（传入 ``db.conn``；
``as txn`` 让出的是上下文管理器本身而非连接，不能作为 conn 传入）。

约定（.trellis/tasks/10-10-pve-persistence-transaction-foundation/design.md）：

* 叶子提交门控：每个公开写方法收尾时调用 :meth:`BaseRepository._commit_if_standalone`，
  只有 ``conn._txn_depth == 0``（自己就是事务所有者，或使用裸连接的测试/迁移）
  才真正 ``commit``，因此被包进调用方事务时绝不提前提交。
* 幂等：写入一律 insert-or-read（``ON CONFLICT DO NOTHING`` + 回读），唯一键冲突
  时返回既有行并报告 ``created=False``，不产生第二条事实、不抛异常。
* 并发：条件写入（CAS）以 ``cas_version`` 为前像，不匹配返回 ``False`` 交调用方
  重读重算；跨任务串行化由 ``DataBase.transaction()`` 负责，仓储自身不开事务。
* 时间：所有时间戳由调用方显式传入（可注入时钟），本模块绝不调用
  ``datetime.now()``；北京时间自然日键由 :func:`shanghai_date_key` 生成，
  不受部署机器时区影响。

玩家气血的 CAS 不新增版本列（避免侵入 child A 已归档的健康语义），而是以
``(current_hp, health_recovered_at)`` 值对作为健康前像版本：写事务内前像不匹配
即返回冲突，旧战报不得强套到已被其他写入移动过的气血上。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

_SHANGHAI = ZoneInfo("Asia/Shanghai")
# 列名会被拼进 SQL（SET/WHERE 片段），只允许迁移文件里出现的纯小写下划线标识符。
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# 历练结算状态机的取值域（child C，design §1）。schema 层已带 CHECK 兜住非法
# 值，这里的常量是给服务层写状态转移用的单一命名来源，避免散落的裸字符串。
STATE_ADVENTURING = "adventuring"
STATE_PENDING_CHOICE = "pending_choice"
STATE_READY_COMBAT = "ready_combat"
STATE_RESOLVED_WIN = "resolved_win"
STATE_RESOLVED_LOSS = "resolved_loss"
STATE_RESOLVED_FLED = "resolved_fled"
SETTLEMENT_STATES = (
    STATE_ADVENTURING,
    STATE_PENDING_CHOICE,
    STATE_READY_COMBAT,
    STATE_RESOLVED_WIN,
    STATE_RESOLVED_LOSS,
    STATE_RESOLVED_FLED,
)
# 终态：进入后只能被读取渲染，不得再被任何转移改写（重放路径的判据）
TERMINAL_STATES = frozenset(
    {STATE_RESOLVED_WIN, STATE_RESOLVED_LOSS, STATE_RESOLVED_FLED}
)
# 非终态：玩家名下「还挂着」的结算行，用于迎战/逃跑入口与重启找回
OPEN_STATES = frozenset({STATE_ADVENTURING, STATE_PENDING_CHOICE, STATE_READY_COMBAT})
# 效果类型封闭取值（design §2.3）：历练消费者的三类副作用，claim 幂等键的一部分
EFFECT_BASE_REWARD = "base_reward"
EFFECT_ROUTE_DROPS = "route_drops"
EFFECT_LEGACY_TRIGGER = "legacy_trigger"
# 消费者身份：历练结算本身，写死一处避免各处拼字符串
CONSUMER_ADVENTURE_SETTLEMENT = "adventure_settlement"
# state → outcome 派生标签（design §1：outcome 只是人类可读标签，
# 读取一律以 state 为权威，禁止两处各自判断）
STATE_OUTCOMES = {
    "resolved_win": "win",
    "resolved_loss": "lose",
    "resolved_fled": "flee",
}


def settlement_outcome(state: str) -> str:
    """Return the human-readable ``outcome`` label derived from ``state``.

    Args:
        state: A settlement state value from ``SETTLEMENT_STATES``.

    Returns:
        ``"win"``/``"lose"``/``"flee"`` for terminal states, ``""`` while the
        run is still open. 只作派生标签：读取一律以 ``state`` 为权威。
    """
    return STATE_OUTCOMES.get(state, "")


def snapshot_text(snapshot: Mapping[str, Any] | str) -> str:
    """Serialize a settlement snapshot for the ``snapshot`` TEXT column.

    Args:
        snapshot: Mapping to encode, or already-encoded JSON text.

    Returns:
        Compact JSON string (empty mapping yields ``"{}"``).
    """
    if isinstance(snapshot, str):
        return snapshot or "{}"
    return json.dumps(snapshot or {}, ensure_ascii=False, separators=(",", ":"))


def shanghai_date_key(now: float | int | datetime) -> str:
    """Convert a timestamp to the ``Asia/Shanghai`` natural-day key ``YYYY-MM-DD``.

    每日次数类唯一键必须按北京自然日切分，部署机器时区不得影响结果。该键
    **不参与** GM 时间快进：快进只移动参与到期判定的绝对时间戳字段，字段跳前
    不得顺手重置每日次数。

    Args:
        now: unix 秒（``int``/``float``）或 ``datetime``（naive 视为 UTC）。

    Returns:
        ``"YYYY-MM-DD"`` 形式的北京时间自然日键。
    """
    moment = (
        now
        if isinstance(now, datetime)
        else datetime.fromtimestamp(int(now), tz=timezone.utc)
    )
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_SHANGHAI).strftime("%Y-%m-%d")


def _as_json(payload: Mapping[str, Any] | str | None) -> str:
    """Normalize a payload into the JSON TEXT stored in SQLite."""
    if payload is None:
        return "{}"
    if isinstance(payload, str):
        return payload or "{}"
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _checked_ident(name: str) -> str:
    """Validate a column identifier before it is interpolated into SQL.

    Args:
        name: Candidate column name used as a SET/WHERE identifier.

    Returns:
        The validated name.

    Raises:
        ValueError: If the name is not a plain lowercase SQL identifier.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"非法列名：{name!r}")
    return name


class BaseRepository:
    """Shared transaction-leaf plumbing for the PVE repositories.

    Args:
        conn: Active aiosqlite connection — pass ``db.conn`` (inside
            ``async with db.transaction():`` the manager yields itself, not
            a connection, so ``txn`` must never be passed here). The
            repository never opens or nests transactions itself.
    """

    def __init__(self, conn: aiosqlite.Connection):
        """Bind the repository to a connection that may already be in a transaction."""
        self.conn = conn

    async def _commit_if_standalone(self) -> None:
        """Commit only when this call is not nested inside an owner transaction.

        ``_txn_depth`` 由 ``DataBase.connect()`` 在连接上初始化，只在
        ``DataBase.transaction()`` 持有期间非零。裸 ``aiosqlite.connect``
        （迁移与单元测试）没有该属性 → ``getattr`` 取默认 0 → 自行提交，
        两种用法都正确。
        """
        if getattr(self.conn, "_txn_depth", 0) == 0:
            await self.conn.commit()

    async def _fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        """Run a SELECT and return the first row as a dict (``None`` when empty)."""
        cursor = await self.conn.execute(sql, tuple(params))
        row = await cursor.fetchone()
        columns = [d[0] for d in cursor.description] if row is not None else []
        await cursor.close()
        if row is None:
            return None
        return dict(zip(columns, row))

    async def _fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        """Run a SELECT and return every row as a dict."""
        cursor = await self.conn.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description] if rows else []
        await cursor.close()
        return [dict(zip(columns, row)) for row in rows]

    async def _insert_or_read(
        self,
        table: str,
        columns: Sequence[str],
        values: Sequence[Any],
        *,
        key_where: str,
        key_params: Sequence[Any],
    ) -> tuple[dict, bool]:
        """Insert one row ignoring unique-conflicts, then read the row back.

        Args:
            table: Target table name.
            columns: Column names matching ``values``.
            values: Bound parameter values.
            key_where: WHERE fragment locating the idempotency-key row.
            key_params: Bound parameters for ``key_where``.

        Returns:
            ``(row, created)``：``created`` 为真表示本次调用真正插入（rowcount==1），
            为假表示唯一键已存在、返回的是既有行（幂等重放）。

        Raises:
            RuntimeError: If the row cannot be read back after the insert attempt —
                这只可能是外键不满足等编程错误，静默返回 None 会让调用方误判。
        """
        cols = ", ".join(_checked_ident(c) for c in columns)
        marks = ", ".join("?" for _ in columns)
        cursor = await self.conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT DO NOTHING",
            tuple(values),
        )
        created = cursor.rowcount == 1
        await cursor.close()
        row = await self._fetchone(
            f"SELECT * FROM {table} WHERE {key_where}", key_params
        )
        if row is None:  # pragma: no cover - 编程错误路径
            raise RuntimeError(f"{table} 写入后回读失败：{key_where}")
        return row, created

    async def _update_where(
        self,
        table: str,
        *,
        keys: Mapping[str, Any],
        values: Mapping[str, Any],
        expected_cas_version: int | None = None,
    ) -> bool:
        """Apply a guarded single-row UPDATE and report whether it matched.

        Args:
            table: Target table.
            keys: Equality predicates identifying the row.
            values: Columns to write (bound, never interpolated).
            expected_cas_version: When not ``None``, the row's ``cas_version`` must
                equal it and is bumped as part of the write（版本化 CAS）；为
                ``None`` 时只做值对条件更新，供没有 ``cas_version`` 列的既有表使用
                （如 ``players`` 的健康值对）。

        Returns:
            ``True`` if exactly one row was updated, ``False`` if no row matched.

        Raises:
            ValueError: If ``values`` is empty, a column name is not a plain
                identifier, or a versioned CAS is asked to write ``cas_version``.
        """
        if not values:
            raise ValueError("条件更新至少需要一个列值")
        sets = ", ".join(f"{_checked_ident(c)} = ?" for c in values)
        params: list[Any] = list(values.values())
        where = [f"{_checked_ident(c)} = ?" for c in keys]
        params.extend(keys.values())
        if expected_cas_version is None:
            guard = ""
        else:
            if "cas_version" in values:
                raise ValueError("cas_version 由 CAS 原语自动递增，不得由调用方写入")
            where.append("cas_version = ?")
            params.append(int(expected_cas_version))
            guard = ", cas_version = cas_version + 1"
        cursor = await self.conn.execute(
            f"UPDATE {table} SET {sets}{guard} WHERE {' AND '.join(where)}",
            tuple(params),
        )
        moved = cursor.rowcount == 1
        await cursor.close()
        return moved

    async def cas_update_player_health(
        self,
        *,
        user_id: str,
        expected_current_hp: int,
        expected_health_recovered_at: int,
        new_current_hp: int,
        new_health_recovered_at: int | None = None,
    ) -> bool:
        """Conditionally write back player 气血 guarded by the health before-image.

        历练结算与世界 Boss 挑战都要把战斗结果写回 ``players``，二者可能并发；
        健康前像 ``(current_hp, health_recovered_at)`` 就是这里的版本号（``players``
        没有 ``cas_version`` 列，加列会侵入 child A 已归档的健康语义）。锚点列
        ``health_recovered_at`` 不参与 GM 时间快进，因此值对比较是稳定的。

        Args:
            user_id: Player row to update.
            expected_current_hp: 气血 read in the caller's short read.
            expected_health_recovered_at: Recovery anchor read alongside it.
            new_current_hp: 气血 to write (clamped by the caller, never < 1 floor
                由领域侧规则决定，本原语只负责不加检查地写)。
            new_health_recovered_at: New anchor; ``None`` keeps the current one.

        Returns:
            ``True`` if the before-image matched and the row moved, ``False`` on
            conflict（调用方必须重读重算，不得重试强套旧战报）。
        """
        values: dict[str, Any] = {"current_hp": int(new_current_hp)}
        if new_health_recovered_at is not None:
            values["health_recovered_at"] = int(new_health_recovered_at)
        moved = await self._update_where(
            "players",
            keys={
                "user_id": user_id,
                "current_hp": int(expected_current_hp),
                "health_recovered_at": int(expected_health_recovered_at),
            },
            values=values,
        )
        await self._commit_if_standalone()
        return moved

    async def get_player_health(self, user_id: str) -> dict | None:
        """Read the health before-image columns used by the CAS above."""
        return await self._fetchone(
            "SELECT user_id, current_hp, health_recovered_at FROM players "
            "WHERE user_id = ?",
            (user_id,),
        )


class AdventureRepository(BaseRepository):
    """Idempotent settlement / effect-claim / fatigue persistence for adventures.

    历练结算事实是 child C 的输出面、后续效果消费者的幂等输入：一次 adventure
    run 至多一条结算，消费者按 ``(consumer_name, settlement_id, effect_type)``
    条件 claim。本仓储不含逃跑判定、战斗结算与任何奖励发放。
    """

    async def get_settlement(self, settlement_id: str) -> dict | None:
        """Fetch a settlement fact by its primary key."""
        return await self._fetchone(
            "SELECT * FROM adventure_settlements WHERE settlement_id = ?",
            (settlement_id,),
        )

    async def get_settlement_by_run(self, adventure_run_id: str) -> dict | None:
        """Fetch a settlement fact by its idempotency key (the adventure run id)."""
        return await self._fetchone(
            "SELECT * FROM adventure_settlements WHERE adventure_run_id = ?",
            (adventure_run_id,),
        )

    async def get_open_settlement(self, user_id: str) -> dict | None:
        """Fetch the player's newest settlement still open (not a terminal state).

        迎战/逃跑入口和进程重启后的找回都以此为权威：查数据库，不查内存字典。

        Args:
            user_id: Player whose open settlement is looked up.

        Returns:
            The newest row whose ``state`` is in ``OPEN_STATES``, else ``None``.
        """
        placeholders = ", ".join("?" for _ in OPEN_STATES)
        return await self._fetchone(
            f"SELECT * FROM adventure_settlements "
            f"WHERE user_id = ? AND state IN ({placeholders}) "
            f"ORDER BY settled_at DESC, rowid DESC LIMIT 1",
            (user_id, *sorted(OPEN_STATES)),
        )

    async def get_latest_settlement(self, user_id: str) -> dict | None:
        """Fetch the player's most recently created settlement, any state.

        「完成历练」在忙碌行已清之后仍要能发现「终态已提交、效果未 claim 完」
        的单子（崩溃点 3 唯一的补发入口），所以这里不按状态过滤；取最新一张用
        ``rowid`` 插入序，不用 ``settled_at``：child C 起结算行在开局就落单，
        该列此时写的是**落单时刻**，要到终态 CAS 才被覆写成真正的结算时刻，
        所以它对在途/终态行都非零、不表示先后（见 :meth:`insert_settlement`）。

        Args:
            user_id: Player whose newest settlement is looked up.

        Returns:
            The newest row of that player, or ``None`` when never settled.
        """
        return await self._fetchone(
            "SELECT * FROM adventure_settlements WHERE user_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (user_id,),
        )

    async def insert_settlement(
        self,
        *,
        settlement_id: str,
        adventure_run_id: str,
        user_id: str,
        now: int,
        encounter_id: str = "",
        profile_id: str = "",
        profile_version: int = 0,
        risk_level: int = 0,
        outcome: str = "",
        hp_before: int = 0,
        hp_after: int = 0,
        fled: bool = False,
        defeated: bool = False,
        state: str = STATE_ADVENTURING,
        route_key: str = "",
        snapshot: Mapping[str, Any] | str = "",
    ) -> tuple[dict, bool]:
        """Insert one adventure settlement fact, or read back the existing row.

        ``adventure_run_id`` 带 UNIQUE 约束：同一 run 重放（重试/重复结算）返回
        既有行且 ``created=False``，绝不产生第二条事实。

        v39 状态机三列（child C）：``state`` 是权威状态、``route_key`` 记归属
        路线、``snapshot`` 记锁定时刻的不可变输入（dict 自动序列化成 JSON）。
        非法 ``state`` 由 schema 的 CHECK 直接拒绝（抛 IntegrityError），不在
        仓储层静默纠正——取值域留在 schema 层是 v39 的有意选择。

        Args:
            settlement_id: Caller-generated primary key for the fact.
            adventure_run_id: Idempotency key of the adventure run.
            user_id: Owner of the run（外键引用 ``players``）.
            now: Timestamp written into ``settled_at``. child C 起结算行在开局
                就落单，故对非终态行它是**落单时刻**；终态 CAS 会把该列覆写
                成真正的结算时刻（判断是否已结算一律看 ``state``，别拿它比 0）。
            encounter_id: Encounter definition being settled.
            profile_id: Enemy profile id from the content design.
            profile_version: Pinned profile version of that encounter.
            risk_level: Risk tier recorded at settlement time.
            outcome: Domain outcome label (``"win"``/``"lose"``/``"flee"`` …).
            hp_before: Player 气血 before the fight.
            hp_after: Player 气血 after the fight（真实气血差 = before - after）。
            fled: Whether the player fled.
            defeated: Whether the enemy was defeated.
            state: One of ``SETTLEMENT_STATES``（开始历练时通常是 adventuring）。
            route_key: Route this settlement belongs to.
            snapshot: Locked combat inputs as a mapping or JSON text.

        Returns:
            ``(row, created)``。
        """
        row, created = await self._insert_or_read(
            "adventure_settlements",
            (
                "settlement_id",
                "adventure_run_id",
                "user_id",
                "encounter_id",
                "profile_id",
                "profile_version",
                "risk_level",
                "outcome",
                "hp_before",
                "hp_after",
                "fled",
                "defeated",
                "settled_at",
                "state",
                "route_key",
                "snapshot",
            ),
            (
                settlement_id,
                adventure_run_id,
                user_id,
                encounter_id,
                profile_id,
                profile_version,
                risk_level,
                outcome,
                int(hp_before),
                int(hp_after),
                int(bool(fled)),
                int(bool(defeated)),
                int(now),
                state,
                route_key,
                snapshot_text(snapshot),
            ),
            key_where="adventure_run_id = ?",
            key_params=(adventure_run_id,),
        )
        await self._commit_if_standalone()
        return row, created

    async def cas_update_settlement(
        self,
        settlement_id: str,
        *,
        expected_cas_version: int,
        expected_state: str | None = None,
        **values: Any,
    ) -> bool:
        """Conditionally update a settlement fact guarded by its CAS version.

        Args:
            settlement_id: Row to update.
            expected_cas_version: Version read in the caller's short read.
            expected_state: 可选前态守护（design §2.2）：状态机推进必须
                ``WHERE state = <前态>``，双击「迎战」的败者才不会把同一场战斗
                结算第二次。省略时退化为纯版本 CAS。
            **values: Columns to write (keyword args; ``cas_version`` 由原语管理).

        Returns:
            ``True`` if updated, ``False`` on version conflict.
        """
        keys = {"settlement_id": settlement_id}
        if expected_state is not None:
            keys["state"] = expected_state
        moved = await self._update_where(
            "adventure_settlements",
            keys=keys,
            expected_cas_version=expected_cas_version,
            values=values,
        )
        await self._commit_if_standalone()
        return moved

    async def claim_effect(
        self,
        *,
        consumer_name: str,
        settlement_id: str,
        effect_type: str,
        now: int,
    ) -> bool:
        """Claim one effect for one consumer; report whether the claim was granted.

        条件 claim：唯一键 ``(consumer_name, settlement_id, effect_type)`` 插入成功
        即领取成功，已存在返回 ``False``。重复投递/重复结算因此不会重复发放。

        Args:
            consumer_name: Stable identity of the consuming subsystem.
            settlement_id: Settlement fact being consumed.
            effect_type: Stable effect key within that settlement.
            now: Claim timestamp (caller clock).

        Returns:
            ``True`` 表示本次调用首次领取该效果。
        """
        cursor = await self.conn.execute(
            "INSERT INTO adventure_effects "
            "(consumer_name, settlement_id, effect_type, claimed_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (consumer_name, settlement_id, effect_type, int(now)),
        )
        claimed = cursor.rowcount == 1
        await cursor.close()
        await self._commit_if_standalone()
        return claimed

    async def list_effect_claims(self, settlement_id: str) -> list[dict]:
        """List every effect claim recorded against one settlement (audit surface)."""
        return await self._fetchall(
            "SELECT * FROM adventure_effects WHERE settlement_id = ? "
            "ORDER BY effect_type, consumer_name",
            (settlement_id,),
        )

    async def get_fatigue(self, user_id: str) -> dict | None:
        """Fetch the persistent fatigue row of a player (``None`` = never tired)."""
        return await self._fetchone(
            "SELECT * FROM adventure_fatigue WHERE user_id = ?", (user_id,)
        )

    async def set_fatigue(
        self,
        *,
        user_id: str,
        route_id: str,
        fatigue_until: int,
        settlement_id: str = "",
    ) -> dict:
        """Upsert the persistent fatigue window of a player.

        疲劳取代进程内 ``_route_cooldowns`` 字典（重启即丢）；``fatigue_until``
        是参与到期判定的绝对时间戳，已登记 GM 时间快进（child P step 5）。

        Args:
            user_id: Fatigued player（外键引用 ``players``）.
            route_id: Route the fatigue belongs to.
            fatigue_until: Expiry timestamp in unix seconds; 0 clears the window.
            settlement_id: Settlement that produced the fatigue (audit trail).

        Returns:
            The stored row after the upsert.
        """
        await self.conn.execute(
            "INSERT INTO adventure_fatigue "
            "(user_id, route_id, fatigue_until, last_settlement_id) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "route_id = excluded.route_id, "
            "fatigue_until = excluded.fatigue_until, "
            "last_settlement_id = excluded.last_settlement_id, "
            "cas_version = adventure_fatigue.cas_version + 1",
            (user_id, route_id, int(fatigue_until), settlement_id),
        )
        await self._commit_if_standalone()
        return await self.get_fatigue(user_id)  # type: ignore[return-value]

    async def cas_clear_fatigue(
        self, user_id: str, *, expected_cas_version: int
    ) -> bool:
        """Clear fatigue only if nobody else moved the row since the caller read it.

        Args:
            user_id: Player whose fatigue is expiring.
            expected_cas_version: Row version from the caller's read.

        Returns:
            ``True`` if cleared, ``False`` on version conflict.
        """
        moved = await self._update_where(
            "adventure_fatigue",
            keys={"user_id": user_id},
            expected_cas_version=expected_cas_version,
            values={"fatigue_until": 0, "route_id": ""},
        )
        await self._commit_if_standalone()
        return moved


class WorldBossRepository(BaseRepository):
    """Instance / challenge / daily-counter / ledger primitives for world bosses.

    生命周期状态机（active → defeated/dissipated）、阶段推进与唯一末击判定属于
    child D 的领域逻辑；本仓储只提供带 CAS 的实例写入、幂等的挑战记录、
    条件累加的次数与贡献，以及按主键/唯一键的读取契约。
    """

    async def get_instance(self, instance_id: str) -> dict | None:
        """Fetch a boss instance row by primary key."""
        return await self._fetchone(
            "SELECT * FROM world_boss_instances WHERE instance_id = ?", (instance_id,)
        )

    async def list_instances(
        self, *, states: Sequence[str] = ("active",), limit: int = 50
    ) -> list[dict]:
        """List instances in the given lifecycle states, soonest expiry first."""
        if not states:
            return []
        marks = ", ".join("?" for _ in states)
        return await self._fetchall(
            f"SELECT * FROM world_boss_instances WHERE state IN ({marks}) "
            "ORDER BY expires_at, instance_id LIMIT ?",
            (*states, int(limit)),
        )

    async def insert_instance(
        self,
        *,
        instance_id: str,
        profile_id: str,
        profile_version: int,
        max_hp: int,
        now: int,
        expires_at: int,
        boss_name: str = "",
        boss_level: int = 0,
        atk: int = 0,
        defense: int = 0,
        agility: int = 0,
        speed: int = 0,
        armor_value: int = 0,
        birth_snapshot: Mapping[str, Any] | str = "",
    ) -> tuple[dict, bool]:
        """Create one instance row, or read back the row a previous call created.

        出生快照（技能、阶段阈值与倍率等）在生成时从档案复制一次并冻结，
        之后热更新 config 不影响进行中的实例；``profile_version`` 记录复制时
        使用的档案版本，供结算与内容追溯。

        Args:
            instance_id: Caller-generated id（同时是幂等键）.
            profile_id: World-boss profile id from the content design.
            profile_version: Pinned profile version for this instance.
            max_hp: Snapshot HP ceiling; also seeds ``current_hp``.
            now: Spawn timestamp (unix seconds, caller clock).
            expires_at: 48h lifecycle deadline（可被 GM 时间快进前移）.
            boss_name: Display name copied from the profile.
            boss_level: Profile level（只记录，不套用旧表经验换算）.
            atk: Snapshot attack.
            defense: Snapshot defense.
            agility: Snapshot agility.
            speed: Snapshot speed.
            armor_value: Snapshot armor.
            birth_snapshot: Immutable copy of the remaining profile fields the
                fight needs（mapping 序列化为 JSON TEXT）.

        Returns:
            ``(row, created)``；同一 ``instance_id`` 重放返回既有行 + ``False``。
        """
        row, created = await self._insert_or_read(
            "world_boss_instances",
            (
                "instance_id",
                "profile_id",
                "profile_version",
                "boss_name",
                "boss_level",
                "max_hp",
                "current_hp",
                "atk",
                "defense",
                "agility",
                "speed",
                "armor_value",
                "birth_snapshot",
                "spawned_at",
                "expires_at",
            ),
            (
                instance_id,
                profile_id,
                profile_version,
                boss_name,
                boss_level,
                int(max_hp),
                int(max_hp),
                atk,
                defense,
                agility,
                speed,
                armor_value,
                _as_json(birth_snapshot),
                int(now),
                int(expires_at),
            ),
            key_where="instance_id = ?",
            key_params=(instance_id,),
        )
        await self._commit_if_standalone()
        return row, created

    async def cas_update_instance(
        self,
        instance_id: str,
        *,
        expected: Mapping[str, Any],
        **values: Any,
    ) -> bool:
        """Conditionally update an instance from the before-image the caller read.

        伤害写回与终态转换都走本方法：``expected`` 携带短读中参与校验的列
        （``state``/``current_hp``/``expires_at`` 等），且必须包含读到的
        ``cas_version`` —— 任何一列不匹配即返回冲突，并发挑战中失败的一方
        必须重读重算，不能把旧战报强套到已被移动过的实例上。漏传
        ``cas_version`` 直接报错：静默按 0 处理会伪装成永远的版本冲突。

        Args:
            instance_id: Row to update.
            expected: Extra predicate columns beyond the primary key; must
                include ``cas_version`` from the caller's short read.
            **values: Columns to write.

        Returns:
            ``True`` if updated, ``False`` if the row moved underneath the caller.
        """
        if "cas_version" not in expected:
            raise ValueError(
                "expected must carry cas_version from the caller's read; "
                "omitting it would masquerade as a permanent version conflict"
            )
        expected_version = int(expected["cas_version"])
        keys: dict[str, Any] = {k: v for k, v in expected.items() if k != "cas_version"}
        keys["instance_id"] = instance_id
        moved = await self._update_where(
            "world_boss_instances",
            keys=keys,
            expected_cas_version=expected_version,
            values=values,
        )
        await self._commit_if_standalone()
        return moved

    async def get_challenge(self, challenge_id: str) -> dict | None:
        """Fetch a challenge fact by its request idempotency key."""
        return await self._fetchone(
            "SELECT * FROM world_boss_challenges WHERE challenge_id = ?",
            (challenge_id,),
        )

    async def list_challenges(
        self, instance_id: str, *, limit: int = 100
    ) -> list[dict]:
        """List challenge facts of one instance, most recent first."""
        return await self._fetchall(
            "SELECT * FROM world_boss_challenges WHERE instance_id = ? "
            "ORDER BY attempted_at DESC, challenge_id LIMIT ?",
            (instance_id, int(limit)),
        )

    async def record_challenge(
        self,
        *,
        challenge_id: str,
        instance_id: str,
        user_id: str,
        date_key: str,
        damage_dealt: int,
        hp_before: int,
        hp_after: int,
        player_hp_before: int,
        player_hp_after: int,
        instance_cas_version: int,
        now: int,
        outcome: str = "",
        fled: bool = False,
        is_last_hit: bool = False,
        phase_changed: int = 0,
    ) -> tuple[dict, bool]:
        """Record one successful challenge fact, idempotent on ``challenge_id``.

        只有成功 CAS 的挑战才应调用本方法（「只有成功尝试消耗次数」由调用方与
        :meth:`increment_daily_attempts` 同事务保证）；同一 ``challenge_id`` 重放
        返回既有行 + ``created=False``，不会二次记账。``damage_dealt`` 必须等于
        ``hp_before - hp_after``（提交时的真实伤害），不得用 ``max_hp - final_hp`` 重算。

        Args:
            challenge_id: Request idempotency key.
            instance_id: Boss instance fought.
            user_id: Challenger.
            date_key: ``Asia/Shanghai`` natural day of the attempt.
            damage_dealt: Real committed damage.
            hp_before: Instance HP before this challenge.
            hp_after: Instance HP after this challenge.
            player_hp_before: Player 气血 before the fight.
            player_hp_after: Player 气血 after the fight.
            instance_cas_version: Instance version this challenge succeeded against.
            now: Attempt timestamp (caller clock).
            outcome: Domain outcome label.
            fled: Whether the player fled.
            is_last_hit: Whether this challenge landed the unique killing blow.
            phase_changed: Phase the instance advanced to (0 = no phase event).

        Returns:
            ``(row, created)``。
        """
        row, created = await self._insert_or_read(
            "world_boss_challenges",
            (
                "challenge_id",
                "instance_id",
                "user_id",
                "date_key",
                "outcome",
                "damage_dealt",
                "hp_before",
                "hp_after",
                "player_hp_before",
                "player_hp_after",
                "fled",
                "is_last_hit",
                "phase_changed",
                "instance_cas_version",
                "attempted_at",
            ),
            (
                challenge_id,
                instance_id,
                user_id,
                date_key,
                outcome,
                int(damage_dealt),
                int(hp_before),
                int(hp_after),
                int(player_hp_before),
                int(player_hp_after),
                int(bool(fled)),
                int(bool(is_last_hit)),
                int(phase_changed),
                int(instance_cas_version),
                int(now),
            ),
            key_where="challenge_id = ?",
            key_params=(challenge_id,),
        )
        await self._commit_if_standalone()
        return row, created

    async def get_daily_attempts(self, *, date_key: str, user_id: str) -> dict | None:
        """Fetch the per-player daily attempt counter for one natural day."""
        return await self._fetchone(
            "SELECT * FROM world_boss_daily_attempts "
            "WHERE date_key = ? AND user_id = ?",
            (date_key, user_id),
        )

    async def increment_daily_attempts(
        self, *, date_key: str, user_id: str, limit: int
    ) -> dict | None:
        """Atomically consume one daily attempt, refusing when the cap is reached.

        种子行 + 单语句条件累加（``WHERE attempts_used < ?``）；上限来自档案
        ``daily_attempts``（child D PRD R3：每名玩家每个北京自然日最多 3 次，
        跨 Boss 全局计数）。达到上限或前像被移动时返回 ``None``，不扣次数。

        Args:
            date_key: ``Asia/Shanghai`` natural-day key.
            user_id: Challenger whose counter is consumed.
            limit: Maximum attempts allowed for that natural day.

        Returns:
            Incremented counter row, or ``None`` when no attempt was consumed.
        """
        await self.conn.execute(
            "INSERT INTO world_boss_daily_attempts (date_key, user_id, attempts_used) "
            "VALUES (?, ?, 0) ON CONFLICT(date_key, user_id) DO NOTHING",
            (date_key, user_id),
        )
        cursor = await self.conn.execute(
            "UPDATE world_boss_daily_attempts "
            "SET attempts_used = attempts_used + 1, cas_version = cas_version + 1 "
            "WHERE date_key = ? AND user_id = ? AND attempts_used < ?",
            (date_key, user_id, int(limit)),
        )
        moved = cursor.rowcount == 1
        await cursor.close()
        await self._commit_if_standalone()
        if not moved:
            return None
        return await self.get_daily_attempts(date_key=date_key, user_id=user_id)

    async def get_ledger(self, challenge_id: str) -> dict | None:
        """Fetch the contribution ledger entry produced by one challenge."""
        return await self._fetchone(
            "SELECT * FROM world_boss_ledger WHERE challenge_id = ?", (challenge_id,)
        )

    async def record_ledger(
        self,
        *,
        instance_id: str,
        challenge_id: str,
        user_id: str,
        profile_version: int,
        damage_dealt: int,
        now: int,
    ) -> tuple[dict, bool]:
        """Append the per-challenge contribution fact (idempotent per challenge).

        Args:
            instance_id: Boss instance the damage landed on.
            challenge_id: Challenge whose damage is recorded（唯一键）.
            user_id: Damager.
            profile_version: Profile version in force for the instance.
            damage_dealt: Real committed damage.
            now: Recording timestamp (caller clock).

        Returns:
            ``(row, created)``；``created=False`` 表示该挑战的台账已存在。
        """
        row, created = await self._insert_or_read(
            "world_boss_ledger",
            (
                "instance_id",
                "challenge_id",
                "user_id",
                "profile_version",
                "damage_dealt",
                "recorded_at",
            ),
            (
                instance_id,
                challenge_id,
                user_id,
                profile_version,
                int(damage_dealt),
                int(now),
            ),
            key_where="challenge_id = ?",
            key_params=(challenge_id,),
        )
        await self._commit_if_standalone()
        return row, created

    async def get_contribution(self, *, instance_id: str, user_id: str) -> dict | None:
        """Fetch a player's cumulative contribution to one instance."""
        return await self._fetchone(
            "SELECT * FROM world_boss_contributions "
            "WHERE instance_id = ? AND user_id = ?",
            (instance_id, user_id),
        )

    async def list_contributions(
        self, instance_id: str, *, limit: int = 100
    ) -> list[dict]:
        """List contributions to one instance, largest damage first."""
        return await self._fetchall(
            "SELECT * FROM world_boss_contributions WHERE instance_id = ? "
            "ORDER BY total_damage DESC, last_hit_at ASC LIMIT ?",
            (instance_id, int(limit)),
        )

    async def accumulate_contribution(
        self,
        *,
        instance_id: str,
        user_id: str,
        profile_version: int,
        damage_dealt: int,
        now: int,
        is_last_hit: bool = False,
    ) -> dict:
        """Accumulate one player's contribution within the caller's unit of work.

        单语句 upsert：``total_damage``/``attempt_count`` 累加，``first_hit_at``
        只在缺失时写入，``last_hit_at`` 覆盖，``is_last_hit`` 一旦被置位就不再被
        非末击抹掉（唯一末击者的判定由 child D 的挑战 CAS 负责，这里只做记录）。

        Args:
            instance_id: Boss instance being accumulated against.
            user_id: Damaging player.
            profile_version: Profile version of the instance.
            damage_dealt: Real damage of this challenge.
            now: Hit timestamp (caller clock).
            is_last_hit: Whether this challenge was the killing blow.

        Returns:
            The contribution row after the upsert.
        """
        await self.conn.execute(
            "INSERT INTO world_boss_contributions "
            "(instance_id, user_id, profile_version, total_damage, attempt_count, "
            "first_hit_at, last_hit_at, is_last_hit) "
            "VALUES (?, ?, ?, ?, 1, ?, ?, ?) "
            "ON CONFLICT(instance_id, user_id) DO UPDATE SET "
            "total_damage = world_boss_contributions.total_damage "
            "+ excluded.total_damage, "
            "attempt_count = world_boss_contributions.attempt_count + 1, "
            "first_hit_at = CASE WHEN world_boss_contributions.first_hit_at = 0 "
            "THEN excluded.first_hit_at "
            "ELSE world_boss_contributions.first_hit_at END, "
            "last_hit_at = excluded.last_hit_at, "
            "is_last_hit = MAX(world_boss_contributions.is_last_hit, "
            "excluded.is_last_hit), "
            "profile_version = excluded.profile_version, "
            "cas_version = world_boss_contributions.cas_version + 1",
            (
                instance_id,
                user_id,
                profile_version,
                int(damage_dealt),
                int(now),
                int(now),
                int(bool(is_last_hit)),
            ),
        )
        await self._commit_if_standalone()
        return await self.get_contribution(  # type: ignore[return-value]
            instance_id=instance_id, user_id=user_id
        )


class OutboxRepository(BaseRepository):
    """Business-event append and per-destination delivery claim primitives.

    事务内只做「写事件 + 建投递记录 + claim/状态迁移」；真正的网络发送必须在
    事务外进行（design §5）。已 ``sent`` 的目标不因其他目标失败而重放；
    ``uncertain``（无法证明请求未发出）永不自动回收重投，只能由管理员人工处理。
    """

    async def get_event(self, event_id: str) -> dict | None:
        """Fetch an event row by primary key."""
        return await self._fetchone(
            "SELECT * FROM business_events WHERE event_id = ?", (event_id,)
        )

    async def get_event_by_business_key(self, business_key: str) -> dict | None:
        """Fetch an event row by its unique business key (idempotency lookup)."""
        return await self._fetchone(
            "SELECT * FROM business_events WHERE business_key = ?", (business_key,)
        )

    async def append_event(
        self,
        *,
        event_id: str,
        business_key: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        occurred_at: int,
        payload: Mapping[str, Any] | str = "",
    ) -> tuple[dict, bool]:
        """Append a business event, or read back the event a previous call inserted.

        Args:
            event_id: Caller-generated event row id.
            business_key: Unique business identity of the fact（幂等键）.
            event_type: Event type label for renderers and consumers.
            aggregate_type: Owning aggregate (e.g. ``"adventure_settlement"``).
            aggregate_id: Row id of the owning aggregate.
            occurred_at: Fact timestamp (unix seconds, caller clock).
            payload: Event payload（mapping 序列化为 JSON TEXT）.

        Returns:
            ``(row, created)``；同一 ``business_key`` 重放不产生第二条事件。
        """
        row, created = await self._insert_or_read(
            "business_events",
            (
                "event_id",
                "business_key",
                "event_type",
                "aggregate_type",
                "aggregate_id",
                "payload",
                "occurred_at",
            ),
            (
                event_id,
                business_key,
                event_type,
                aggregate_type,
                aggregate_id,
                _as_json(payload),
                int(occurred_at),
            ),
            key_where="business_key = ?",
            key_params=(business_key,),
        )
        await self._commit_if_standalone()
        return row, created

    async def add_delivery(
        self, *, event_id: str, platform: str, group_id: str, now: int
    ) -> tuple[dict, bool]:
        """Queue one destination for an event (idempotent per destination).

        Args:
            event_id: Event to deliver.
            platform: Target platform id (e.g. ``"aiocqhttp"``).
            group_id: Target group id.
            now: Queueing timestamp, also the initial retry watermark.

        Returns:
            ``(row, created)``；重复投递同一目标返回既有行 + ``False``。
        """
        row, created = await self._insert_or_read(
            "event_deliveries",
            ("event_id", "platform", "group_id", "next_retry_at", "updated_at"),
            (event_id, platform, group_id, int(now), int(now)),
            key_where="event_id = ? AND platform = ? AND group_id = ?",
            key_params=(event_id, platform, group_id),
        )
        await self._commit_if_standalone()
        return row, created

    async def get_delivery(self, delivery_id: int) -> dict | None:
        """Fetch one delivery row by id."""
        return await self._fetchone(
            "SELECT * FROM event_deliveries WHERE delivery_id = ?", (int(delivery_id),)
        )

    async def list_deliveries(
        self, *, states: Sequence[str] = ("queued",), now: int = 0, limit: int = 50
    ) -> list[dict]:
        """List deliveries in the given states whose retry watermark has passed."""
        if not states:
            return []
        marks = ", ".join("?" for _ in states)
        return await self._fetchall(
            f"SELECT * FROM event_deliveries WHERE state IN ({marks}) "
            "AND next_retry_at <= ? ORDER BY next_retry_at, delivery_id LIMIT ?",
            (*states, int(now), int(limit)),
        )

    async def claim_delivery(
        self, delivery_id: int, *, owner: str, lease_until: int, now: int
    ) -> dict | None:
        """Claim one queued delivery for a dispatcher; ``None`` if not claimable.

        只认领 ``queued`` 且已到重试时间的记录。租约过期的 ``dispatching`` 与
        ``uncertain`` 都不在此被回收 —— 无法证明请求未发出的陈旧 claim 必须经
        :meth:`list_stale_dispatching` 暴露、由人工判定后转 ``uncertain``，
        不得自动重投（本系统不承诺 exactly-once）。

        Args:
            delivery_id: Delivery row to claim.
            owner: Dispatcher identity holding the lease.
            lease_until: Lease expiry timestamp (unix seconds, caller clock).
            now: Claim timestamp; also the retry-due watermark.

        Returns:
            The delivery row in ``dispatching`` state (含新的 ``cas_version`` 与
            ``attempt_count``)，未抢到或未到时间时返回 ``None``。
        """
        cursor = await self.conn.execute(
            "UPDATE event_deliveries "
            "SET state = 'dispatching', claim_owner = ?, claim_expires_at = ?, "
            "attempt_count = attempt_count + 1, updated_at = ?, "
            "cas_version = cas_version + 1 "
            "WHERE delivery_id = ? AND state = 'queued' AND next_retry_at <= ?",
            (owner, int(lease_until), int(now), int(delivery_id), int(now)),
        )
        moved = cursor.rowcount == 1
        await cursor.close()
        await self._commit_if_standalone()
        if not moved:
            return None
        return await self.get_delivery(delivery_id)

    async def list_stale_dispatching(self, *, now: int, limit: int = 50) -> list[dict]:
        """List ``dispatching`` rows whose lease expired (manual triage surface)."""
        return await self._fetchall(
            "SELECT * FROM event_deliveries "
            "WHERE state = 'dispatching' AND claim_expires_at <= ? "
            "ORDER BY claim_expires_at, delivery_id LIMIT ?",
            (int(now), int(limit)),
        )

    async def complete_delivery(
        self,
        delivery_id: int,
        *,
        owner: str,
        expected_cas_version: int,
        state: str,
        now: int,
        error: str = "",
        retry_at: int = 0,
    ) -> bool:
        """Move a delivery this dispatcher holds to ``sent``/``queued``/``uncertain``.

        前像是 ``claim_owner`` + ``cas_version``：租约被他人接管后原持有者的写入
        必然失败，因此不会出现两个 dispatcher 同时改写同一投递记录。

        Args:
            delivery_id: Row to update.
            owner: Claim holder allowed to write this transition.
            expected_cas_version: Version returned by :meth:`claim_delivery`.
            state: ``"sent"``（已送达）、``"queued"``（确证未发出，可自动重试）、
                ``"uncertain"``（可能已发出，禁止自动重试）。
            now: Transition timestamp (caller clock).
            error: Last error text for failed transitions.
            retry_at: Next retry watermark; only meaningful for ``"queued"``.

        Returns:
            ``True`` if the transition applied, ``False`` on owner/version conflict.

        Raises:
            ValueError: If ``state`` is not one of the three legal outcomes.
        """
        if state not in ("sent", "queued", "uncertain"):
            raise ValueError(f"非法投递状态：{state!r}")
        moved = await self._update_where(
            "event_deliveries",
            keys={"delivery_id": int(delivery_id), "claim_owner": owner},
            expected_cas_version=expected_cas_version,
            values={
                "state": state,
                "claim_owner": "",
                "claim_expires_at": 0,
                "last_error": error,
                # 只有回到 queued 才保留重试水位；sent/uncertain 清零避免
                # 后续人工重放时被旧的 next_retry_at 意外挡住。
                "next_retry_at": int(retry_at) if state == "queued" else 0,
                "updated_at": int(now),
            },
        )
        await self._commit_if_standalone()
        return moved
