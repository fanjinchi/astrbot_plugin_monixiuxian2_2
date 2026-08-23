# handlers/impart_handlers.py
from astrbot.api.event import AstrMessageEvent

from ..data.data_manager import DataBase
from ..managers.impart_manager import ImpartManager
from ..models import Player
from .utils import player_required


class ImpartHandlers:
    """Handlers for the impart (传承) system commands: info and activation."""

    def __init__(self, db: DataBase, impart_mgr: ImpartManager):
        self.db = db
        self.impart_mgr = impart_mgr

    async def handle_impart_info(self, event: AstrMessageEvent):
        """传承信息：列出全部持有实例并标注激活项"""
        user_id = event.get_sender_id()
        instances = await self.impart_mgr.list_owner_legacies(user_id)
        yield event.plain_result(self.impart_mgr.build_panel(instances))

    @player_required
    async def handle_impart_activate(
        self, player: Player, event: AstrMessageEvent, target: str = ""
    ):
        """激活传承：选择一条持有的传承作为修炼累积目标"""
        instances = await self.impart_mgr.list_owner_legacies(player.user_id)
        if not instances:
            yield event.plain_result(
                "❌ 你尚未持有任何传承。\n"
                "获取途径：宗门宝库领取 / 历练与秘境机缘触发（需先战胜守护者）。"
            )
            return

        target = (target or "").strip().lstrip("#")
        # isdecimal 而非 isdigit：isdigit 对 '²' 等上标数字返回 True 但 int() 会抛 ValueError
        if target.isdecimal():
            instance_id = int(target)
            ok, msg = await self.impart_mgr.activate_legacy(player.user_id, instance_id)
            yield event.plain_result(msg)
            return

        # 无参数或参数非法：列出可激活的传承
        lines = ["✨ 选择要激活的传承", "━━━━━━━━━━━━━━━"]
        for inst in instances:
            name = self.impart_mgr.get_type_name(inst.legacy_type)
            mark = "🌟当前激活" if inst.is_active else ""
            lines.append(
                f"#{inst.id}【{name}】传承值{inst.impart_value} {mark}".rstrip()
            )
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("💡 用法：/激活传承 <编号>（如：/激活传承 3）")
        lines.append("出关时仅激活中的传承累积传承值。")
        yield event.plain_result("\n".join(lines))
