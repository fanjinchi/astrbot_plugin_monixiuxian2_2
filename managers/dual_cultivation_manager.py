"""双修系统管理器"""

import time
from typing import Any

from astrbot.api import logger

from ..core.cultivation_manager import CultivationManager
from ..data import DataBase
from ..models import Player
from ..models_extended import UserStatus

__all__ = ["DualCultivationManager"]

# 双修配置
DUAL_CULT_COOLDOWN = 3600  # 1小时冷却
DUAL_CULT_REQUEST_EXPIRE = 300  # 请求过期时间（5分钟）
DUAL_CULT_MAX_EXP_RATIO = 3.0  # 双修双方修为差距最大3倍


class DualCultivationManager:
    """双修管理器"""

    def __init__(self, db: DataBase, config: Any, config_manager: Any):
        """Initialize the dual-cultivation manager.

        Args:
            db: The plugin database instance.
            config: AstrBot-style configuration object (used for base EXP/min).
            config_manager: Plugin ConfigManager for game_config access.
        """
        self.db = db
        self.config = config
        self.config_manager = config_manager
        self._cultivation_manager = CultivationManager(config, config_manager, None)

    def _get_k_hours(self) -> int:
        """Return the fixed dual-cultivation duration in hours."""
        return self.config_manager.game_config.get("dual_cultivation", {}).get(
            "k_hours", 2
        )

    def _get_cooldown(self) -> int:
        """Return the dual-cultivation cooldown in seconds from game_config."""
        return self.config_manager.game_config.get("dual_cultivation", {}).get(
            "cooldown", DUAL_CULT_COOLDOWN
        )

    def _get_request_expire(self) -> int:
        """Return the dual-cultivation request expiry in seconds from game_config."""
        return self.config_manager.game_config.get("dual_cultivation", {}).get(
            "request_expire", DUAL_CULT_REQUEST_EXPIRE
        )

    def _get_base_exp_per_minute(self) -> int:
        """Return the base cultivation EXP per minute, matching closed cultivation."""
        return self.config.get("VALUES", {}).get("BASE_EXP_PER_MINUTE", 100)

    def _get_realm_factor(self, level_index: int) -> float:
        """Calculate the realm factor f(t) for a player level.

        t is the 1-based major-realm index (levels 1-10 -> 1, 11-20 -> 2, ...).
        The configured mode maps to:
        - linear:   f(t) = t
        - power1.5: f(t) = t^1.5
        - power2:   f(t) = t^2

        Unknown modes fall back to linear and emit a warning.

        Args:
            level_index: 1-based player level index.

        Returns:
            The realm factor as a float.
        """
        t = (level_index - 1) // 10 + 1
        mode = self.config_manager.game_config.get("dual_cultivation", {}).get(
            "realm_factor", "linear"
        )
        if mode == "linear":
            return float(t)
        if mode == "power1.5":
            return float(t**1.5)
        if mode == "power2":
            return float(t * t)
        logger.warning(
            f"Unknown dual-cultivation realm_factor '{mode}', falling back to linear."
        )
        return float(t)

    def _calculate_exp_gain(self, player: Player) -> int:
        """Calculate the fixed dual-cultivation EXP gain for a player.

        Formula: K hours * BASE_EXP_PER_MINUTE * 60 * root_speed * f(t).
        The gain depends only on the player's own level and spiritual root.

        Args:
            player: The player receiving the reward.

        Returns:
            Integer EXP gained.
        """
        k_hours = self._get_k_hours()
        base_exp_per_minute = self._get_base_exp_per_minute()
        root_speed = self._cultivation_manager.get_spiritual_root_speed(player)
        realm_factor = self._get_realm_factor(player.level_index)
        return int(k_hours * base_exp_per_minute * 60 * root_speed * realm_factor)

    def get_help_text(self) -> str:
        """Return the user-facing description of the dual-cultivation reward."""
        k_hours = self._get_k_hours()
        cooldown_minutes = self._get_cooldown() // 60
        return (
            f"双修可获得定额修为收益：K={k_hours}小时闭关等效 × 境界系数 × 灵根倍率。\n"
            f"冷却时间：{cooldown_minutes}分钟"
        )

    async def _create_request(
        self, from_id: str, from_name: str, target_id: str
    ) -> int:
        """创建双修请求（持久化到数据库）"""
        now = int(time.time())
        expires_at = now + self._get_request_expire()

        # 先清理该目标的旧请求
        await self.db.conn.execute(
            "DELETE FROM dual_cultivation_requests WHERE target_id = ?", (target_id,)
        )

        await self.db.conn.execute(
            """
            INSERT INTO dual_cultivation_requests (from_id, from_name, target_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (from_id, from_name, target_id, now, expires_at),
        )
        await self.db.conn.commit()

        async with self.db.conn.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def _get_pending_request(self, target_id: str) -> dict | None:
        """获取待处理的双修请求"""
        now = int(time.time())

        # 清理过期请求
        await self.db.conn.execute(
            "DELETE FROM dual_cultivation_requests WHERE expires_at < ?", (now,)
        )
        await self.db.conn.commit()

        async with self.db.conn.execute(
            """
            SELECT id, from_id, from_name, target_id, created_at, expires_at
            FROM dual_cultivation_requests
            WHERE target_id = ? AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (target_id, now),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "from_id": row[1],
                    "from_name": row[2],
                    "target_id": row[3],
                    "created_at": row[4],
                    "expires_at": row[5],
                }
            return None

    async def _delete_request(self, request_id: int):
        """删除双修请求"""
        await self.db.conn.execute(
            "DELETE FROM dual_cultivation_requests WHERE id = ?", (request_id,)
        )
        await self.db.conn.commit()

    async def send_request(self, initiator: Player, target_id: str) -> tuple[bool, str]:
        """发起双修请求"""
        if initiator.user_id == target_id:
            return False, "❌ 不能与自己双修。"

        # 检查发起者状态（状态互斥）
        user_cd = await self.db.ext.get_user_cd(initiator.user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            return False, f"❌ 你当前正{current_status}，无法发起双修！"

        # 检查目标是否存在
        target = await self.db.get_player_by_id(target_id)
        if not target:
            return False, "❌ 对方还未踏入修仙之路。"

        # 检查修为差距
        exp_ratio = max(initiator.experience, target.experience) / max(
            min(initiator.experience, target.experience), 1
        )
        if exp_ratio > DUAL_CULT_MAX_EXP_RATIO:
            return (
                False,
                f"❌ 双方修为差距过大（最大{DUAL_CULT_MAX_EXP_RATIO}倍），无法双修。",
            )

        # 检查目标状态
        target_cd = await self.db.ext.get_user_cd(target_id)
        if target_cd and target_cd.type != UserStatus.IDLE:
            return False, "❌ 对方正忙，无法接受双修请求。"

        # 检查发起者冷却
        last_dual = await self._get_last_dual_time(initiator.user_id)
        now = int(time.time())
        cooldown = self._get_cooldown()
        if last_dual and (now - last_dual) < cooldown:
            remaining = cooldown - (now - last_dual)
            return False, f"❌ 双修冷却中，还需 {remaining // 60} 分钟。"

        # 检查目标冷却
        target_last_dual = await self._get_last_dual_time(target_id)
        if target_last_dual and (now - target_last_dual) < cooldown:
            remaining = cooldown - (now - target_last_dual)
            return False, f"❌ 对方正在双修冷却，还需 {remaining // 60} 分钟。"

        # 发起请求（持久化到数据库）
        await self._create_request(
            initiator.user_id, initiator.user_name or initiator.user_id[:8], target_id
        )

        return True, (
            f"💕 已向【{target.user_name or target_id[:8]}】发起双修请求！\n"
            f"对方使用 /接受双修 或 /拒绝双修 响应。\n"
            f"请求将在{self._get_request_expire() // 60}分钟后过期。"
        )

    async def accept_request(self, acceptor: Player) -> tuple[bool, str]:
        """接受双修请求"""
        request = await self._get_pending_request(acceptor.user_id)
        if not request:
            return False, "❌ 没有待处理的双修请求。"

        initiator = await self.db.get_player_by_id(request["from_id"])
        if not initiator:
            await self._delete_request(request["id"])
            return False, "❌ 请求发起者数据异常。"

        # 再次检查修为差距
        exp_ratio = max(initiator.experience, acceptor.experience) / max(
            min(initiator.experience, acceptor.experience), 1
        )
        if exp_ratio > DUAL_CULT_MAX_EXP_RATIO:
            await self._delete_request(request["id"])
            return False, "❌ 双方修为差距已超过限制，双修取消。"

        now = int(time.time())
        cooldown = self._get_cooldown()

        # 检查双方冷却时间（防止请求期间冷却尚未结束）
        acceptor_last_dual = await self._get_last_dual_time(acceptor.user_id)
        if acceptor_last_dual and (now - acceptor_last_dual) < cooldown:
            await self._delete_request(request["id"])
            remaining = cooldown - (now - acceptor_last_dual)
            return False, f"❌ 你的双修冷却中，还需 {remaining // 60} 分钟。"

        initiator_last_dual = await self._get_last_dual_time(initiator.user_id)
        if initiator_last_dual and (now - initiator_last_dual) < cooldown:
            await self._delete_request(request["id"])
            remaining = cooldown - (now - initiator_last_dual)
            return False, f"❌ 对方仍在双修冷却，还需 {remaining // 60} 分钟。"

        # 计算双修收益（按各自境界独立计算，与对方修为无关）
        init_exp_gain = self._calculate_exp_gain(initiator)
        accept_exp_gain = self._calculate_exp_gain(acceptor)

        init_root_speed = self._cultivation_manager.get_spiritual_root_speed(initiator)
        accept_root_speed = self._cultivation_manager.get_spiritual_root_speed(acceptor)
        init_t = (initiator.level_index - 1) // 10 + 1
        accept_t = (acceptor.level_index - 1) // 10 + 1
        init_factor = self._get_realm_factor(initiator.level_index)
        accept_factor = self._get_realm_factor(acceptor.level_index)

        # 应用收益
        initiator.experience += init_exp_gain
        acceptor.experience += accept_exp_gain
        await self.db.update_player(initiator)
        await self.db.update_player(acceptor)

        # 记录冷却
        await self._set_last_dual_time(initiator.user_id, now)
        await self._set_last_dual_time(acceptor.user_id, now)

        # 清除请求
        await self._delete_request(request["id"])

        initiator_name = initiator.user_name or initiator.user_id[:8]
        acceptor_name = acceptor.user_name or acceptor.user_id[:8]

        return True, (
            f"💕 双修成功！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"与【{initiator_name}】双修\n"
            f"{initiator_name} 获得修为：+{init_exp_gain:,}\n"
            f"（境界系数 t={init_t}, f(t)={init_factor:.1f}，灵根倍率 {init_root_speed:.2f}）\n"
            f"你（{acceptor_name}）获得修为：+{accept_exp_gain:,}\n"
            f"（境界系数 t={accept_t}, f(t)={accept_factor:.1f}，灵根倍率 {accept_root_speed:.2f}）\n"
            f"━━━━━━━━━━━━━━━\n"
            f"下次双修：{self._get_cooldown() // 60}分钟后"
        )

    async def reject_request(self, rejecter_id: str) -> tuple[bool, str]:
        """拒绝双修请求"""
        request = await self._get_pending_request(rejecter_id)
        if not request:
            return False, "❌ 没有待处理的双修请求。"

        from_name = request["from_name"]
        await self._delete_request(request["id"])

        return True, f"已拒绝【{from_name}】的双修请求。"

    async def _get_last_dual_time(self, user_id: str) -> int | None:
        """获取上次双修时间"""
        async with self.db.conn.execute(
            "SELECT last_dual_time FROM dual_cultivation WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def _set_last_dual_time(self, user_id: str, timestamp: int):
        """设置上次双修时间"""
        await self.db.conn.execute(
            """
            INSERT INTO dual_cultivation (user_id, last_dual_time)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_dual_time = excluded.last_dual_time
            """,
            (user_id, timestamp),
        )
        await self.db.conn.commit()
