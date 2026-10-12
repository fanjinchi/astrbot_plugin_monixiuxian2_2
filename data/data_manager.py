# data/data_manager.py

import asyncio
import json
from dataclasses import fields
from pathlib import Path

import aiosqlite

from astrbot.api import logger

from ..models import Player
from .database_extended import DatabaseExtended

# 获取 Player 模型的所有字段名（用于过滤数据库中的多余字段，作为迁移未完成时的兼容）
PLAYER_FIELDS = {f.name for f in fields(Player)}

# 从 Player dataclass 动态生成 SQL
_PLAYER_FIELDS = [f.name for f in fields(Player)]
_PLAYER_FIELDS_SET = set(_PLAYER_FIELDS)

# 领域独占列：health_recovered_at（懒恢复锚点）只能由 HealthService 的
# settle/_write_anchor 直写（core/health.py），绝不随 update_player 落库。
# 调用方持有的内存 Player 副本不承载权威锚点——结算把锚点前移后，若陈旧的
# 内存值再被全字段 UPDATE 刷回数据库，已结算的恢复窗口会复活（重复回血、
# 忙碌窗口被补上血，违反 AC4）。INSERT（创角）仍写入该列（默认 0）。
_DOMAIN_OWNED_FIELDS = frozenset({"health_recovered_at"})
_UPDATE_FIELDS = [f for f in _PLAYER_FIELDS if f not in _DOMAIN_OWNED_FIELDS]


def _build_insert_sql():
    """构建 INSERT SQL（从 Player dataclass 动态生成）"""
    cols = ", ".join(_PLAYER_FIELDS)
    placeholders = ", ".join(["?" for _ in _PLAYER_FIELDS])
    return f"INSERT INTO players ({cols}) VALUES ({placeholders})"


def _build_update_sql():
    """构建 UPDATE SQL（从 Player dataclass 动态生成，排除领域独占列）"""
    set_clauses = ", ".join([f"{f} = ?" for f in _UPDATE_FIELDS if f != "user_id"])
    return f"UPDATE players SET {set_clauses} WHERE user_id = ?"


def _player_to_tuple(player: Player, for_insert: bool = True):
    """将 Player 对象转换为 SQL 参数元组"""
    values = []
    for f in _PLAYER_FIELDS if for_insert else _UPDATE_FIELDS:
        val = getattr(player, f)
        # 布尔值转整数
        if isinstance(val, bool):
            val = int(val)
        values.append(val)
    if not for_insert:
        # UPDATE: user_id 移到最后
        values.append(values.pop(0))
    return tuple(values)


class TxnState:
    """One-shot abort flag carrier shared by all layers of one transaction.

    Created by the transaction owner on entry; inner (no-op join) layers share
    the same instance through ``conn._txn_state``; discarded by the owner on
    exit, so the abort marker never outlives its transaction.
    """

    def __init__(self):
        self.aborted = False


class _TransactionCM:
    """Async context manager implementing the unit-of-work protocol (design D1/D1.2).

    Ownership rules:
    - The layer that issues ``BEGIN IMMEDIATE`` is the **owner**; only it may
      commit/rollback on exit. Inner same-task layers are passive (they only
      decrement the depth counter and never touch commit/rollback).
    - Cross-task entry serializes on ``DataBase._txn_free``: waiters park until
      the current owner exits, then claim ownership **while holding the
      condition lock** and issue BEGIN only after releasing it (compensation
      path clears the ownership fields inside the lock if BEGIN fails or the
      claimer is cancelled at the BEGIN await point).
    - ``txn.abort()`` sets a marker on the shared TxnState; on clean exit the
      owner rolls back without re-raising.
    - ``__aexit__`` branches on ``exc_type is not None`` (BaseException-safe;
      never ``except Exception`` — CancelledError/GeneratorExit would leak an
      open transaction otherwise).

    Transition constraint (documented, not enforced): this CM must never be
    entered inside a raw ``BEGIN IMMEDIATE`` block — the AST scan of the 26
    production blocks verified no such nesting (design D1).
    """

    def __init__(self, db: "DataBase"):
        self._db = db
        self._state: TxnState | None = None
        self._joined = False  # True = passive inner layer (no BEGIN issued)

    @property
    def aborted(self) -> bool:
        """Whether a clean exit will roll back instead of commit (design D3)."""
        return bool(self._state and self._state.aborted)

    async def __aenter__(self) -> "_TransactionCM":
        db = self._db
        conn = db.conn
        if conn is None:
            raise RuntimeError("database is not connected")
        current_task = asyncio.current_task()
        if current_task is None:
            # bd mxt guard: the ownership test below compares task identity,
            # and 'None is None' is True — a task-less caller on an unowned
            # connection would be mistaken for a same-task join (no BEGIN, no
            # ownership, nothing committed on exit). The CM is only meaningful
            # inside a Task (handlers and timers always are), so fail fast
            # instead of silently dropping the transaction boundary.
            raise RuntimeError(
                "transaction() requires a running asyncio task "
                "(asyncio.current_task() returned None)"
            )
        if conn._txn_owner_task is current_task:
            # Same-task fast path: no-op join, share the existing state.
            # Never touches the condition — zero overhead on the single-task path.
            conn._txn_depth += 1
            self._joined = True
            self._state = conn._txn_state
            return self
        # Cross-task claim path (design D1.2 lock-in claim + compensation).
        async with db._txn_free:
            while conn._txn_owner_task is not None:
                await db._txn_free.wait()
            # Claimed while holding the lock: at most one task can be inside
            # this section, so at most one BEGIN is ever issued per handover.
            conn._txn_owner_task = current_task
            conn._txn_depth = 1
            conn._txn_state = TxnState()
            self._state = conn._txn_state
            self._joined = False
        try:
            await conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            # Compensation (design D1.2 #3): clear ownership inside the lock,
            # wake every waiter, attempt a best-effort rollback (safe no-op
            # when BEGIN never took effect), then re-raise.
            async with db._txn_free:
                conn._txn_owner_task = None
                conn._txn_depth = 0
                conn._txn_state = None
                db._txn_free.notify_all()
            try:
                await conn.rollback()
            except Exception:
                pass  # Best effort; the original error is what matters.
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        db = self._db
        conn = db.conn
        if self._joined:
            # Passive inner layer: decrement depth only; the owner commits or
            # rolls back. Exceptions propagate untouched.
            if conn is not None:
                # bd ip5 guard: never let the depth go negative. ``conn`` is
                # re-read from ``db.conn`` here rather than captured at enter,
                # so if the handle was replaced while this layer was alive
                # (ensure_connection() → reconnect() → connect() rebuilds the
                # connection and resets _txn_depth/_txn_owner_task/_txn_state on
                # the NEW one), this decrement would land on a fresh depth of 0.
                # A negative depth makes every helper's 'depth == 0' commit gate
                # permanently false → writes linger uncommitted. Clamp at 0 and
                # warn: the joined transaction went away with the old handle.
                if conn._txn_depth <= 0:
                    logger.warning(
                        "[database] joined transaction layer exited on a depth-0 "
                        f"connection (depth={conn._txn_depth}); the transaction it "
                        "joined was lost with a replaced connection — keeping depth at 0"
                    )
                conn._txn_depth = max(0, conn._txn_depth - 1)
            return False
        # Owner layer (F2 reset order: depth → owner → state → notify inside
        # the lock, all in finally so a failing commit/rollback leaves no
        # residue).
        try:
            if exc_type is not None:
                await conn.rollback()
            elif self._state is not None and self._state.aborted:
                await conn.rollback()  # abort on clean exit: rollback, no raise
            else:
                try:
                    await conn.commit()
                except BaseException:
                    # Commit failed: the transaction may still be open — roll it
                    # back before raising so a later helper does not commit
                    # someone else's open transaction.
                    try:
                        await conn.rollback()
                    except Exception:
                        pass
                    raise
        finally:
            conn._txn_depth = 0
            conn._txn_owner_task = None
            conn._txn_state = None
            async with db._txn_free:
                db._txn_free.notify_all()
        return False

    def abort(self):
        """Mark the transaction for rollback (idempotent, never raises).

        After abort(), writes inside the block are still executed but will be
        rolled back when the owner exits; a clean exit then rolls back without
        re-raising (design D1 abort contract).
        """
        if self._state is not None:
            self._state.aborted = True


class DataBase:
    """数据库管理类，提供基础玩家操作"""

    def __init__(self, db_file: str = "xiuxian_data_lite.db"):
        self.db_path = Path(db_file)
        self.conn: aiosqlite.Connection = None
        self.ext: DatabaseExtended | None = None  # 扩展操作类
        # Cross-task mutual exclusion for transaction ownership (design D1.2):
        # waiters park on this condition until the current owner exits.
        self._txn_free = asyncio.Condition()

    async def connect(self):
        """连接数据库"""
        # Pin the sqlite3 default isolation_level="" explicitly (design D0): the
        # whole CM/helper-gating reasoning relies on implicit BEGIN/DML and the
        # 42 flag-less data-layer leaf commits rely on implicit per-DML
        # transaction atomicity. Python 3.12's autocommit attribute or a driver
        # default change would silently alter both behaviors — make it visible.
        self.conn = await aiosqlite.connect(self.db_path, isolation_level="")
        self.conn.row_factory = aiosqlite.Row
        # Transaction ownership state (design D1/D1.2): depth gate, owner task
        # (identity-compared), and the shared abort-marker carrier. Initialized
        # fresh on every (re)connect; reconnection rebuilds all three.
        self.conn._txn_depth = 0
        self.conn._txn_owner_task = None
        self.conn._txn_state = None
        self.ext = DatabaseExtended(self.conn)  # 初始化扩展操作

    async def close(self):
        """关闭数据库连接"""
        if self.conn:
            try:
                await self.conn.close()
            finally:
                self.conn = None
                self.ext = None

    async def reconnect(self):
        """重连数据库（用于连接意外断开时）"""
        await self.close()
        await self.connect()

    def _connection_alive(self) -> bool:
        """检测底层aiosqlite连接是否仍然可用"""
        if not self.conn:
            return False
        # aiosqlite Connection 在 close 后会将 _connection 置为 None
        return getattr(self.conn, "_connection", None) is not None

    async def ensure_connection(self):
        """确保数据库连接可用，必要时自动重连"""
        if self._connection_alive():
            return
        logger.warning("[database] 检测到数据库连接断开，正在自动重连...")
        await self.reconnect()

    def transaction(self) -> "_TransactionCM":
        """Return the unit-of-work async context manager (design D1/D1.2).

        Same-task nesting is a zero-overhead no-op join (shared TxnState);
        cross-task entry waits on ``_txn_free`` until the owning task exits,
        claims ownership while holding the condition lock, then issues
        ``BEGIN IMMEDIATE`` outside the lock. See ``_TransactionCM`` for the
        full ownership/failure protocol.
        """
        return _TransactionCM(self)

    async def create_player(self, player: Player):
        """创建新玩家（字段从 Player dataclass 动态生成，避免遗漏）"""
        sql = _build_insert_sql()
        params = _player_to_tuple(player, for_insert=True)
        await self.conn.execute(sql, params)
        # D2 ownership gate: commit only outside an active CM transaction
        # (child A step-5 audit: 创角 may run inside a settle+create txn).
        if getattr(self.conn, "_txn_depth", 0) == 0:
            await self.conn.commit()

    async def get_player_by_id(self, user_id: str) -> Player:
        """根据用户ID获取玩家信息"""
        async with self.conn.execute(
            "SELECT * FROM players WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # 过滤掉 Player 模型中不存在的字段（兼容旧数据库/迁移未完成的情况）
                filtered_data = {
                    k: v for k, v in dict(row).items() if k in _PLAYER_FIELDS_SET
                }
                return Player(**filtered_data)
            return None

    async def get_player_by_name(self, user_name: str) -> Player:
        """根据道号获取玩家信息"""
        async with self.conn.execute(
            "SELECT * FROM players WHERE user_name = ?", (user_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                filtered_data = {
                    k: v for k, v in dict(row).items() if k in _PLAYER_FIELDS_SET
                }
                return Player(**filtered_data)
            return None

    async def update_player(self, player: Player):
        """更新玩家信息（字段从 Player dataclass 动态生成，避免遗漏）

        领域独占列 health_recovered_at（懒恢复锚点）不在 UPDATE 之列——
        它只能由 HealthService 结算时直写；调用方内存副本中的锚点值会被
        忽略，永不回写数据库。

        Args:
            player: 玩家对象
        """
        sql = _build_update_sql()
        params = _player_to_tuple(player, for_insert=False)
        await self.conn.execute(sql, params)
        # D2 ownership gate: commit only outside an active CM transaction.
        # Fail-open default 0 keeps legacy standalone semantics for bare conns.
        if getattr(self.conn, "_txn_depth", 0) == 0:
            await self.conn.commit()

    async def delete_player(self, user_id: str):
        """删除玩家"""
        await self.conn.execute("DELETE FROM players WHERE user_id = ?", (user_id,))
        # D2 ownership gate: commit only outside an active CM transaction.
        # Fail-open default 0 keeps legacy standalone semantics for bare conns.
        if getattr(self.conn, "_txn_depth", 0) == 0:
            await self.conn.commit()

    async def delete_player_cascade(self, user_id: str):
        """级联删除玩家及所有关联数据

        Args:
            user_id: 用户ID
            （单语句失败仍由 safe_execute 吞掉并记日志，语义不变）
        """

        async def safe_execute(sql: str, params: tuple):
            """Run one cascade statement, logging and swallowing errors so a missing table does not abort the rest."""
            try:
                await self.conn.execute(sql, params)
            except Exception as e:
                sql_preview = sql.strip().split(" ")[0]
                logger.warning(f"[delete_player_cascade] 忽略执行 {sql_preview}: {e}")

        statements = [
            (
                "UPDATE spirit_eyes SET owner_id = NULL, owner_name = NULL, claim_time = NULL WHERE owner_id = ?",
                (user_id,),
            ),
            ("DELETE FROM player_skills WHERE user_id = ?", (user_id,)),
            ("DELETE FROM blessed_lands WHERE user_id = ?", (user_id,)),
            ("DELETE FROM spirit_farms WHERE user_id = ?", (user_id,)),
            ("DELETE FROM bank_accounts WHERE user_id = ?", (user_id,)),
            (
                "UPDATE bank_loans SET status = 'bad_debt' WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ),
            ("DELETE FROM bounty_tasks WHERE user_id = ?", (user_id,)),
            ("DELETE FROM dual_cultivation WHERE user_id = ?", (user_id,)),
            (
                "DELETE FROM dual_cultivation_requests WHERE from_id = ? OR target_id = ?",
                (user_id, user_id),
            ),
            ("DELETE FROM user_cd WHERE user_id = ?", (user_id,)),
            ("DELETE FROM buff_info WHERE user_id = ?", (user_id,)),
            ("DELETE FROM legacy_instances WHERE owner_id = ?", (user_id,)),
            (
                "DELETE FROM impart_pk_cooldown WHERE challenger_id = ? OR target_id = ?",
                (user_id, user_id),
            ),
            ("DELETE FROM impart_snatch_protection WHERE user_id = ?", (user_id,)),
            ("DELETE FROM combat_cooldowns WHERE user_id = ?", (user_id,)),
            (
                "DELETE FROM pending_gifts WHERE sender_id = ? OR receiver_id = ?",
                (user_id, user_id),
            ),
        ]

        for sql, params in statements:
            await safe_execute(sql, params)

        await self.conn.execute("DELETE FROM players WHERE user_id = ?", (user_id,))
        # D2 ownership gate: commit only outside an active CM transaction.
        # Fail-open default 0 keeps legacy standalone semantics for bare conns.
        if getattr(self.conn, "_txn_depth", 0) == 0:
            await self.conn.commit()

    async def get_all_players(self):
        """获取所有玩家"""
        async with self.conn.execute("SELECT * FROM players") as cursor:
            rows = await cursor.fetchall()
            # 过滤掉 Player 模型中不存在的字段（兼容旧数据库/迁移未完成的情况）
            return [
                Player(
                    **{k: v for k, v in dict(row).items() if k in _PLAYER_FIELDS_SET}
                )
                for row in rows
            ]

    # ===== 商店数据操作 =====

    async def get_shop_data(self, shop_id: str = "global") -> tuple[int, list[dict]]:
        """获取商店数据

        Args:
            shop_id: 商店ID，默认为全局商店

        Returns:
            (last_refresh_time, current_items) 元组
        """
        async with self.conn.execute(
            "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
            (shop_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                last_refresh_time = row[0]
                try:
                    current_items = json.loads(row[1])
                except json.JSONDecodeError:
                    current_items = []
                return last_refresh_time, current_items
            return 0, []

    async def update_shop_data(
        self, shop_id: str, last_refresh_time: int, current_items: list[dict]
    ):
        """更新商店数据

        Args:
            shop_id: 商店ID
            last_refresh_time: 最后刷新时间戳
            current_items: 当前商店物品列表
        """
        items_json = json.dumps(current_items, ensure_ascii=False)
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO shop (shop_id, last_refresh_time, current_items)
            VALUES (?, ?, ?)
            """,
            (shop_id, last_refresh_time, items_json),
        )
        # D2 ownership gate: commit only outside an active CM transaction.
        # Fail-open default 0 keeps legacy standalone semantics for bare conns.
        if getattr(self.conn, "_txn_depth", 0) == 0:
            await self.conn.commit()

    async def decrement_shop_item_stock(
        self,
        shop_id: str,
        item_name: str,
        quantity: int = 1,
    ) -> tuple[bool, int, int]:
        """尝试扣减指定商店物品的库存（原子操作，可批量）

        Args:
            shop_id: 商店ID
            item_name: 物品名称
            quantity: 扣减数量（默认1，最小1）

        Returns:
            (是否成功, last_refresh_time, 扣减后的库存数量)
        """
        quantity = max(1, int(quantity))
        # D2 ownership gate: own the transaction only when no outer CM is
        # active (4.2 收编：外层事务内 join，不另起 BEGIN/commit/rollback)。
        own_txn = getattr(self.conn, "_txn_depth", 0) == 0
        if own_txn:
            await self.conn.execute("BEGIN IMMEDIATE")
        try:
            async with self.conn.execute(
                "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
                (shop_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                if own_txn:
                    await self.conn.rollback()
                return False, 0, 0

            last_refresh_time = row[0]
            try:
                current_items = json.loads(row[1])
            except json.JSONDecodeError:
                current_items = []

            target_index = -1
            for idx, item in enumerate(current_items):
                if item.get("name") == item_name:
                    target_index = idx
                    break

            if target_index == -1:
                if own_txn:
                    await self.conn.rollback()
                return False, last_refresh_time, 0

            stock = current_items[target_index].get("stock", 0)
            if stock is None or stock <= 0:
                if own_txn:
                    await self.conn.rollback()
                return False, last_refresh_time, max(stock or 0, 0)

            if stock < quantity:
                if own_txn:
                    await self.conn.rollback()
                return False, last_refresh_time, stock

            new_stock = stock - quantity
            current_items[target_index]["stock"] = new_stock

            items_json = json.dumps(current_items, ensure_ascii=False)
            await self.conn.execute(
                "UPDATE shop SET current_items = ?, last_refresh_time = ? WHERE shop_id = ?",
                (items_json, last_refresh_time, shop_id),
            )
            if own_txn:
                await self.conn.commit()
            return True, last_refresh_time, new_stock
        except Exception:
            if own_txn:
                await self.conn.rollback()
            raise
