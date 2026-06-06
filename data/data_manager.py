# data/data_manager.py

import aiosqlite
import json
from dataclasses import fields
from pathlib import Path
from typing import Tuple, List, Optional
from astrbot.api import logger
from ..models import Player
from .database_extended import DatabaseExtended

# 获取 Player 模型的所有字段名（用于过滤数据库中的多余字段，作为迁移未完成时的兼容）
PLAYER_FIELDS = {f.name for f in fields(Player)}

# 从 Player dataclass 动态生成 SQL
_PLAYER_FIELDS = [f.name for f in fields(Player)]
_PLAYER_FIELDS_SET = set(_PLAYER_FIELDS)

def _build_insert_sql():
    """构建 INSERT SQL（从 Player dataclass 动态生成）"""
    cols = ', '.join(_PLAYER_FIELDS)
    placeholders = ', '.join(['?' for _ in _PLAYER_FIELDS])
    return f"INSERT INTO players ({cols}) VALUES ({placeholders})"

def _build_update_sql():
    """构建 UPDATE SQL（从 Player dataclass 动态生成）"""
    set_clauses = ', '.join([f"{f} = ?" for f in _PLAYER_FIELDS if f != 'user_id'])
    return f"UPDATE players SET {set_clauses} WHERE user_id = ?"

def _player_to_tuple(player: Player, for_insert: bool = True):
    """将 Player 对象转换为 SQL 参数元组"""
    values = []
    for f in _PLAYER_FIELDS:
        val = getattr(player, f)
        # 布尔值转整数
        if isinstance(val, bool):
            val = int(val)
        values.append(val)
    if not for_insert:
        # UPDATE: user_id 移到最后
        values.append(values.pop(0))
    return tuple(values)



class DataBase:
    """数据库管理类，提供基础玩家操作"""

    def __init__(self, db_file: str = "xiuxian_data_lite.db"):
        self.db_path = Path(db_file)
        self.conn: aiosqlite.Connection = None
        self.ext: Optional[DatabaseExtended] = None  # 扩展操作类

    async def connect(self):
        """连接数据库"""
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
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

    async def create_player(self, player: Player):
        """创建新玩家（字段从 Player dataclass 动态生成，避免遗漏）"""
        sql = _build_insert_sql()
        params = _player_to_tuple(player, for_insert=True)
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def get_player_by_id(self, user_id: str) -> Player:
        """根据用户ID获取玩家信息"""
        async with self.conn.execute(
            "SELECT * FROM players WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # 过滤掉 Player 模型中不存在的字段（兼容旧数据库/迁移未完成的情况）
                filtered_data = {k: v for k, v in dict(row).items() if k in _PLAYER_FIELDS_SET}
                return Player(**filtered_data)
            return None

    async def get_player_by_name(self, user_name: str) -> Player:
        """根据道号获取玩家信息"""
        async with self.conn.execute(
            "SELECT * FROM players WHERE user_name = ?",
            (user_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                filtered_data = {k: v for k, v in dict(row).items() if k in _PLAYER_FIELDS_SET}
                return Player(**filtered_data)
            return None

    async def update_player(self, player: Player):
        """更新玩家信息（字段从 Player dataclass 动态生成，避免遗漏）"""
        sql = _build_update_sql()
        params = _player_to_tuple(player, for_insert=False)
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def delete_player(self, user_id: str):
        """删除玩家"""
        await self.conn.execute(
            "DELETE FROM players WHERE user_id = ?",
            (user_id,)
        )
        await self.conn.commit()

    async def delete_player_cascade(self, user_id: str):
        """级联删除玩家及所有关联数据"""
        async def safe_execute(sql: str, params: tuple):
            try:
                await self.conn.execute(sql, params)
            except Exception as e:
                sql_preview = sql.strip().split(" ")[0]
                logger.warning(f"[delete_player_cascade] 忽略执行 {sql_preview}: {e}")

        statements = [
            ("UPDATE spirit_eyes SET owner_id = NULL, owner_name = NULL, claim_time = NULL WHERE owner_id = ?", (user_id,)),
            ("DELETE FROM blessed_lands WHERE user_id = ?", (user_id,)),
            ("DELETE FROM spirit_farms WHERE user_id = ?", (user_id,)),
            ("DELETE FROM bank_accounts WHERE user_id = ?", (user_id,)),
            ("UPDATE bank_loans SET status = 'bad_debt' WHERE user_id = ? AND status = 'active'", (user_id,)),
            ("DELETE FROM bounty_tasks WHERE user_id = ?", (user_id,)),
            ("DELETE FROM dual_cultivation WHERE user_id = ?", (user_id,)),
            ("DELETE FROM dual_cultivation_requests WHERE from_id = ? OR target_id = ?", (user_id, user_id)),
            ("DELETE FROM user_cd WHERE user_id = ?", (user_id,)),
            ("DELETE FROM buff_info WHERE user_id = ?", (user_id,)),
            ("DELETE FROM impart_info WHERE user_id = ?", (user_id,)),
            ("DELETE FROM combat_cooldowns WHERE attacker_id = ? OR defender_id = ?", (user_id, user_id)),
            ("DELETE FROM pending_gifts WHERE sender_id = ? OR receiver_id = ?", (user_id, user_id)),
        ]

        for sql, params in statements:
            await safe_execute(sql, params)

        await self.conn.execute("DELETE FROM players WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    async def get_all_players(self):
        """获取所有玩家"""
        async with self.conn.execute("SELECT * FROM players") as cursor:
            rows = await cursor.fetchall()
            # 过滤掉 Player 模型中不存在的字段（兼容旧数据库/迁移未完成的情况）
            return [Player(**{k: v for k, v in dict(row).items() if k in _PLAYER_FIELDS_SET}) for row in rows]

    # ===== 商店数据操作 =====

    async def get_shop_data(self, shop_id: str = "global") -> Tuple[int, List[dict]]:
        """获取商店数据

        Args:
            shop_id: 商店ID，默认为全局商店

        Returns:
            (last_refresh_time, current_items) 元组
        """
        async with self.conn.execute(
            "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
            (shop_id,)
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

    async def update_shop_data(self, shop_id: str, last_refresh_time: int, current_items: List[dict]):
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
            (shop_id, last_refresh_time, items_json)
        )
        await self.conn.commit()

    async def decrement_shop_item_stock(self, shop_id: str, item_name: str, quantity: int = 1, external_transaction: bool = False) -> tuple[bool, int, int]:
        """尝试扣减指定商店物品的库存（原子操作，可批量）

        Args:
            shop_id: 商店ID
            item_name: 物品名称
            quantity: 扣减数量（默认1，最小1）
            external_transaction: 是否由外部管理事务（True时不执行内部BEGIN/COMMIT/ROLLBACK）

        Returns:
            (是否成功, last_refresh_time, 扣减后的库存数量)
        """
        quantity = max(1, int(quantity))
        if not external_transaction:
            await self.conn.execute("BEGIN IMMEDIATE")
        try:
            async with self.conn.execute(
                "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
                (shop_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                if not external_transaction:
                    await self.conn.rollback()
                return False, 0, 0

            last_refresh_time = row[0]
            try:
                current_items = json.loads(row[1])
            except json.JSONDecodeError:
                current_items = []

            target_index = -1
            for idx, item in enumerate(current_items):
                if item.get('name') == item_name:
                    target_index = idx
                    break

            if target_index == -1:
                if not external_transaction:
                    await self.conn.rollback()
                return False, last_refresh_time, 0

            stock = current_items[target_index].get('stock', 0)
            if stock is None or stock <= 0:
                if not external_transaction:
                    await self.conn.rollback()
                return False, last_refresh_time, max(stock or 0, 0)

            if stock < quantity:
                if not external_transaction:
                    await self.conn.rollback()
                return False, last_refresh_time, stock

            new_stock = stock - quantity
            current_items[target_index]['stock'] = new_stock

            items_json = json.dumps(current_items, ensure_ascii=False)
            await self.conn.execute(
                "UPDATE shop SET current_items = ?, last_refresh_time = ? WHERE shop_id = ?",
                (items_json, last_refresh_time, shop_id)
            )
            if not external_transaction:
                await self.conn.commit()
            return True, last_refresh_time, new_stock
        except Exception:
            if not external_transaction:
                await self.conn.rollback()
            raise

    async def increment_shop_item_stock(self, shop_id: str, item_name: str, quantity: int = 1):
        """回滚库存（在购买失败时恢复库存），支持批量"""
        quantity = max(1, int(quantity))
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            async with self.conn.execute(
                "SELECT last_refresh_time, current_items FROM shop WHERE shop_id = ?",
                (shop_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                await self.conn.rollback()
                return

            last_refresh_time = row[0]
            try:
                current_items = json.loads(row[1])
            except json.JSONDecodeError:
                current_items = []

            for item in current_items:
                if item.get('name') == item_name:
                    current_stock = item.get('stock', 0) or 0
                    item['stock'] = current_stock + quantity
                    break

            items_json = json.dumps(current_items, ensure_ascii=False)
            await self.conn.execute(
                "UPDATE shop SET current_items = ?, last_refresh_time = ? WHERE shop_id = ?",
                (items_json, last_refresh_time, shop_id)
            )
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise
