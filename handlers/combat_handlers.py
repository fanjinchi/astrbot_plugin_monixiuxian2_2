# handlers/combat_handlers.py
import re
import time

from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.combat_manager import CombatManager
from ..models import Player
from ..models_extended import UserStatus

# 战斗冷却配置（秒）
DUEL_COOLDOWN = 300  # 决斗冷却5分钟
SPAR_COOLDOWN = 60  # 切磋冷却1分钟


class CombatHandlers:
    def __init__(self, db: DataBase, combat_mgr: CombatManager, config_manager=None):
        self.db = db
        self.combat_mgr = combat_mgr
        self.config_manager = config_manager

    async def _get_combat_cooldown(self, user_id: str) -> dict:
        """获取战斗冷却信息"""
        try:
            async with self.db.conn.execute(
                "SELECT last_duel_time, last_spar_time FROM combat_cooldowns WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {"last_duel_time": row[0], "last_spar_time": row[1]}
        except Exception as e:
            from astrbot.api import logger

            logger.warning(f"获取战斗冷却失败: {e}")
        return {"last_duel_time": 0, "last_spar_time": 0}

    async def _update_combat_cooldown(self, user_id: str, combat_type: str):
        """更新战斗冷却时间"""
        now = int(time.time())
        try:
            if combat_type == "duel":
                await self.db.conn.execute(
                    """
                    INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time)
                    VALUES (?, ?, 0)
                    ON CONFLICT(user_id) DO UPDATE SET last_duel_time = ?
                    """,
                    (user_id, now, now),
                )
            else:
                await self.db.conn.execute(
                    """
                    INSERT INTO combat_cooldowns (user_id, last_duel_time, last_spar_time)
                    VALUES (?, 0, ?)
                    ON CONFLICT(user_id) DO UPDATE SET last_spar_time = ?
                    """,
                    (user_id, now, now),
                )
            await self.db.conn.commit()
        except Exception as e:
            from astrbot.api import logger

            logger.warning(f"更新战斗冷却失败: {e}")

    async def _get_target_id(self, event: AstrMessageEvent, arg: str) -> str:
        message_chain = []
        if hasattr(event, "message_obj") and event.message_obj:
            message_chain = getattr(event.message_obj, "message", []) or []

        for component in message_chain:
            if isinstance(component, At):
                candidate = None
                for attr in ("qq", "target", "uin", "user_id"):
                    candidate = getattr(component, attr, None)
                    if candidate:
                        break
                if candidate:
                    return str(candidate).lstrip("@")

        if arg:
            cleaned = arg.strip().lstrip("@")
            if cleaned.isdigit():
                return cleaned

        message_text = ""
        if hasattr(event, "get_message_str"):
            message_text = event.get_message_str() or ""
        match = re.search(r"(\d{5,})", message_text)
        if match:
            return match.group(1)
        return None

    async def _fetch_player(self, user_id: str) -> Player | None:
        """Load player by ID; returns None if not found."""
        return await self.db.get_player_by_id(user_id)

    async def handle_duel(self, event: AstrMessageEvent, target: str):
        """决斗 (消耗气血)"""
        user_id = event.get_sender_id()
        target_id = await self._get_target_id(event, target)

        if not target_id:
            yield event.plain_result("❌ 请指定决斗目标")
            return

        if user_id == target_id:
            yield event.plain_result("❌ 不能和自己决斗")
            return

        # 检查发起者状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正在{current_status}，无法进行战斗！")
            return

        # 检查目标状态
        target_cd = await self.db.ext.get_user_cd(target_id)
        if target_cd and target_cd.type != UserStatus.IDLE:
            target_status = UserStatus.get_name(target_cd.type)
            yield event.plain_result(f"❌ 对方当前正在{target_status}，无法进行战斗！")
            return

        # 检查冷却
        now = int(time.time())
        cooldown = await self._get_combat_cooldown(user_id)
        last_duel = cooldown.get("last_duel_time", 0)
        if last_duel and (now - last_duel) < DUEL_COOLDOWN:
            remaining = DUEL_COOLDOWN - (now - last_duel)
            yield event.plain_result(
                f"❌ 决斗冷却中，还需 {remaining // 60} 分 {remaining % 60} 秒"
            )
            return

        # 获取双方数据
        p1 = await self._fetch_player(user_id)
        p2 = await self._fetch_player(target_id)

        if not p1:
            yield event.plain_result("❌ 你还未踏入修仙之路")
            return
        if not p2:
            yield event.plain_result("❌ 对方还未踏入修仙之路")
            return

        # TODO: impart buff mapping to new attribute system (design pending)

        # 战斗
        result = await self.combat_mgr.player_vs_player(p1, p2, combat_type=2)  # 2=决斗

        # 结算（写入最终气血）
        p1.hp = result["player1_final_hp"]
        p2.hp = result["player2_final_hp"]
        await self.db.update_player(p1)
        await self.db.update_player(p2)

        # 更新冷却
        await self._update_combat_cooldown(user_id, "duel")

        # 生成战报
        log = "\n".join(result["combat_log"])
        yield event.plain_result(f"{log}")

    async def handle_spar(self, event: AstrMessageEvent, target: str):
        """切磋 (不消耗气血)"""
        user_id = event.get_sender_id()
        target_id = await self._get_target_id(event, target)

        if not target_id:
            yield event.plain_result("❌ 请指定切磋目标")
            return

        if user_id == target_id:
            yield event.plain_result("❌ 不能和自己切磋")
            return

        # 检查发起者状态
        user_cd = await self.db.ext.get_user_cd(user_id)
        if user_cd and user_cd.type != UserStatus.IDLE:
            current_status = UserStatus.get_name(user_cd.type)
            yield event.plain_result(f"❌ 你当前正在{current_status}，无法进行战斗！")
            return

        # 检查目标状态
        target_cd = await self.db.ext.get_user_cd(target_id)
        if target_cd and target_cd.type != UserStatus.IDLE:
            target_status = UserStatus.get_name(target_cd.type)
            yield event.plain_result(f"❌ 对方当前正在{target_status}，无法进行战斗！")
            return

        # 检查冷却
        now = int(time.time())
        cooldown = await self._get_combat_cooldown(user_id)
        last_spar = cooldown.get("last_spar_time", 0)
        if last_spar and (now - last_spar) < SPAR_COOLDOWN:
            remaining = SPAR_COOLDOWN - (now - last_spar)
            yield event.plain_result(f"❌ 切磋冷却中，还需 {remaining} 秒")
            return

        p1 = await self._fetch_player(user_id)
        p2 = await self._fetch_player(target_id)

        if not p1 or not p2:
            yield event.plain_result("❌ 双方都需要踏入修仙之路")
            return

        # TODO: impart buff mapping to new attribute system (design pending)

        result = await self.combat_mgr.player_vs_player(p1, p2, combat_type=1)  # 1=切磋

        # 写入最终气血（切磋原本不消耗，但统一引擎可能修正数值）
        p1.hp = result["player1_final_hp"]
        p2.hp = result["player2_final_hp"]
        await self.db.update_player(p1)
        await self.db.update_player(p2)

        # 更新冷却
        await self._update_combat_cooldown(user_id, "spar")

        log = "\n".join(result["combat_log"])
        yield event.plain_result(f"{log}")
