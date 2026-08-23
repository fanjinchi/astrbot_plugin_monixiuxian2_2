# handlers/impart_pk_handlers.py
"""传承挑战处理器（夺取制）"""

import re

from astrbot.api.event import AstrMessageEvent

from ..data import DataBase
from ..managers.impart_pk_manager import ImpartPkManager
from ..models import Player
from .utils import player_required

__all__ = ["ImpartPkHandlers"]


class ImpartPkHandlers:
    """传承挑战处理器"""

    def __init__(self, db: DataBase, impart_pk_mgr: ImpartPkManager):
        self.db = db
        self.impart_pk_mgr = impart_pk_mgr

    @player_required
    async def handle_impart_challenge(
        self, player: Player, event: AstrMessageEvent, target_info: str = ""
    ):
        """发起传承挑战（夺取对方一条非宗门传承）"""
        # 解析目标（可附类型：/传承挑战 @某人 [类型]）
        target_id = self._extract_user_id(target_info)
        if not target_id:
            yield event.plain_result(
                "⚔️ 传承挑战\n"
                "━━━━━━━━━━━━━━━\n"
                "夺取对方持有的一条传承（宗门传承不可夺取）！\n"
                "胜利：夺走对方最近获得的可夺传承（传承进度清零，由你重新修炼）\n"
                "失败：损失1%修为，且5天内不得再挑战此人\n"
                "对方刚被夺走后3日内受保护，无法被挑战\n"
                "━━━━━━━━━━━━━━━\n"
                "💡 用法：/传承挑战 @某人 [类型]\n"
                "类型可选：通用/历练/秘境（不填则取最近获得的可夺传承）"
            )
            return

        if target_id == player.user_id:
            yield event.plain_result("❌ 不能挑战自己。")
            return

        # 可选类型过滤
        legacy_type = self._extract_legacy_type(target_info)

        # 获取目标玩家
        target = await self.db.get_player_by_id(target_id)
        if not target:
            yield event.plain_result("❌ 对方还未踏入修仙之路。")
            return

        # 发起挑战
        wins, log, rewards = await self.impart_pk_mgr.challenge_impart(
            player, target, legacy_type
        )

        # 前置拒绝
        rejected = rewards.get("rejected")
        if rejected:
            yield event.plain_result(f"❌ 无法发起传承挑战：{rejected}")
            return

        # 平局
        if rewards.get("draw"):
            yield event.plain_result(
                "🤝 传承挑战平局！\n"
                "━━━━━━━━━━━━━━━\n"
                f"对手：{target.user_name or target_id[:8]}\n"
                "双方势均力敌，传承未被夺取，你也不受挑战冷却。"
            )
            return

        if wins:
            snatched_name = self.impart_pk_mgr.impart_mgr.get_type_name(
                rewards.get("snatched_type", "common")
            )
            result_msg = (
                "🎉 传承挑战胜利！\n"
                "━━━━━━━━━━━━━━━\n"
                f"对手：{target.user_name or target_id[:8]}\n"
                f"你夺走了对方的【{snatched_name}】！\n"
                "传承进度已清零，需重新修炼解锁等阶奖励。\n"
                "发送「激活传承」可将其设为当前修炼目标。"
            )
        else:
            result_msg = (
                "💀 传承挑战失败...\n"
                "━━━━━━━━━━━━━━━\n"
                f"对手：{target.user_name or target_id[:8]}\n"
                f"损失修为：-{rewards.get('exp_loss', 0):,}\n"
                "且5天内不得再次向该玩家发起传承挑战。"
            )

        yield event.plain_result(result_msg)

    @player_required
    async def handle_impart_ranking(self, player: Player, event: AstrMessageEvent):
        """传承排行榜（按全部传承实例传承值总和）"""
        rankings = await self.impart_pk_mgr.get_impart_ranking(10)

        if not rankings:
            yield event.plain_result("📊 传承排行榜暂无数据。")
            return

        lines = ["🏆 传承排行榜（传承值总和）\n━━━━━━━━━━━━━━━"]
        for i, r in enumerate(rankings, 1):
            lines.append(f"{i}. {r['user_name']} - 传承值{r['impart_value']}")
        lines.append("━━━━━━━━━━━━━━━")
        # 累积周期配置驱动：避免硬编码文案与配置不一致
        impart_cfg = getattr(
            getattr(self.impart_pk_mgr, "impart_mgr", None), "config_manager", None
        )
        every_minutes = 15
        if impart_cfg is not None:
            every_minutes = impart_cfg.impart_config.get(
                "cultivation_points_every_minutes", 15
            )
        lines.append(f"传承值通过闭关修炼累积（每{every_minutes}分钟+1点）")

        yield event.plain_result("\n".join(lines))

    def _extract_user_id(self, msg: str) -> str:
        """从消息中提取用户ID"""
        if not msg:
            return ""
        # 匹配 @xxx 或纯数字
        at_match = re.search(r"\[CQ:at,qq=(\d+)\]", msg)
        if at_match:
            return at_match.group(1)
        # 纯数字
        num_match = re.search(r"(\d{5,12})", msg)
        if num_match:
            return num_match.group(1)
        return ""

    def _extract_legacy_type(self, msg: str) -> str:
        """从消息中提取可选的传承类型过滤词，返回内部类型名或空串。"""
        if not msg:
            return ""
        mapping = {
            "通用": "common",
            "历练": "adventure",
            "秘境": "rift",
        }
        for keyword, legacy_type in mapping.items():
            if keyword in msg:
                return legacy_type
        return ""
